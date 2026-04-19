from __future__ import annotations

from collections import defaultdict

from app.db import Database
from app.schemas import (
    AllocationSummary,
    CategorySummary,
    HoldingInput,
    HoldingRecord,
    SnapshotCreateInput,
    SnapshotRecord,
    TargetRange,
    holding_from_row,
    snapshot_from_row,
)

DEFAULT_TARGET_ALLOCATION = {
    "equity": {"min": 48.0, "max": 55.0},
    "fixed_income": {"min": 35.0, "max": 42.0},
    "cash": {"min": 5.0, "max": 10.0},
    "gold": {"min": 0.0, "max": 5.0},
}

CATEGORY_LABELS = {
    "equity": "权益",
    "fixed_income": "固收",
    "cash": "现金",
    "gold": "黄金",
    "other": "其他",
}


class PortfolioService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_snapshot(self, payload: SnapshotCreateInput) -> SnapshotRecord:
        with self.database.session() as connection:
            cursor = connection.execute(
                """
                INSERT INTO weekly_snapshots (
                    snapshot_date,
                    total_assets,
                    cash_balance,
                    weekly_return_amount,
                    ytd_return_amount,
                    data_cutoff_notes,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.snapshot_date,
                    payload.total_assets,
                    payload.cash_balance,
                    payload.weekly_return_amount,
                    payload.ytd_return_amount,
                    payload.data_cutoff_notes,
                    payload.notes,
                ),
            )
            snapshot_id = cursor.lastrowid

            for holding in payload.holdings:
                self._insert_holding(connection, snapshot_id, holding)

            connection.commit()
            return self.get_snapshot(snapshot_id)

    def update_snapshot(self, snapshot_id: int, payload: SnapshotCreateInput) -> SnapshotRecord:
        with self.database.session() as connection:
            existing = connection.execute(
                "SELECT id FROM weekly_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Snapshot {snapshot_id} not found")

            connection.execute(
                """
                UPDATE weekly_snapshots
                SET snapshot_date = ?,
                    total_assets = ?,
                    cash_balance = ?,
                    weekly_return_amount = ?,
                    ytd_return_amount = ?,
                    data_cutoff_notes = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    payload.snapshot_date,
                    payload.total_assets,
                    payload.cash_balance,
                    payload.weekly_return_amount,
                    payload.ytd_return_amount,
                    payload.data_cutoff_notes,
                    payload.notes,
                    snapshot_id,
                ),
            )
            connection.execute("DELETE FROM holdings WHERE snapshot_id = ?", (snapshot_id,))
            for holding in payload.holdings:
                self._insert_holding(connection, snapshot_id, holding)

            connection.commit()
            return self.get_snapshot(snapshot_id)

    def get_snapshot(self, snapshot_id: int) -> SnapshotRecord:
        with self.database.session() as connection:
            snapshot_row = connection.execute(
                "SELECT * FROM weekly_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()

            if snapshot_row is None:
                raise ValueError(f"Snapshot {snapshot_id} not found")

            holdings = self._get_holdings_for_snapshot(connection, snapshot_id)
            return snapshot_from_row(snapshot_row, holdings)

    def list_snapshots(self) -> list[SnapshotRecord]:
        with self.database.session() as connection:
            snapshot_rows = connection.execute(
                "SELECT * FROM weekly_snapshots ORDER BY snapshot_date DESC"
            ).fetchall()

            snapshots: list[SnapshotRecord] = []
            for row in snapshot_rows:
                holdings = self._get_holdings_for_snapshot(connection, int(row["id"]))
                snapshots.append(snapshot_from_row(row, holdings))

            return snapshots

    def get_allocation_summary(self) -> AllocationSummary:
        snapshots = self.list_snapshots()
        if not snapshots:
            return AllocationSummary(total_assets=0, categories={})

        latest = snapshots[0]
        grouped_amounts: dict[str, float] = defaultdict(float)
        for holding in latest.holdings:
            grouped_amounts[holding.category] += holding.amount

        categories = {
            category: CategorySummary(
                amount=amount,
                percent=round((amount / latest.total_assets) * 100, 2) if latest.total_assets else 0,
            )
            for category, amount in grouped_amounts.items()
        }
        return AllocationSummary(total_assets=latest.total_assets, categories=categories)

    def get_target_allocation(self) -> dict[str, dict[str, float]]:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM target_allocation_settings WHERE id = 1"
            ).fetchone()
            if row is None:
                return DEFAULT_TARGET_ALLOCATION
            return {
                "equity": {"min": float(row["equity_min"]), "max": float(row["equity_max"])},
                "fixed_income": {
                    "min": float(row["fixed_income_min"]),
                    "max": float(row["fixed_income_max"]),
                },
                "cash": {"min": float(row["cash_min"]), "max": float(row["cash_max"])},
                "gold": {"min": float(row["gold_min"]), "max": float(row["gold_max"])},
            }

    def update_target_allocation(
        self, allocation: dict[str, dict[str, float]]
    ) -> dict[str, dict[str, float]]:
        normalized = {
            category: TargetRange(**allocation.get(category, DEFAULT_TARGET_ALLOCATION[category]))
            for category in DEFAULT_TARGET_ALLOCATION
        }
        with self.database.session() as connection:
            connection.execute(
                """
                UPDATE target_allocation_settings
                SET equity_min = ?,
                    equity_max = ?,
                    fixed_income_min = ?,
                    fixed_income_max = ?,
                    cash_min = ?,
                    cash_max = ?,
                    gold_min = ?,
                    gold_max = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (
                    normalized["equity"].min,
                    normalized["equity"].max,
                    normalized["fixed_income"].min,
                    normalized["fixed_income"].max,
                    normalized["cash"].min,
                    normalized["cash"].max,
                    normalized["gold"].min,
                    normalized["gold"].max,
                ),
            )
        return {
            category: {"min": config.min, "max": config.max}
            for category, config in normalized.items()
        }

    def get_portfolio_analysis(self) -> dict:
        snapshots = self.list_snapshots()
        targets = self.get_target_allocation()
        if not snapshots:
            return {"targets": targets, "diagnostics": {}, "suggestions": []}

        latest = snapshots[0]
        grouped_amounts: dict[str, float] = defaultdict(float)
        for holding in latest.holdings:
            grouped_amounts[holding.category] += holding.amount

        diagnostics: dict[str, dict] = {}
        suggestions: list[str] = []
        for category in ("equity", "fixed_income", "cash", "gold"):
            amount = grouped_amounts.get(category, 0.0)
            percent = round((amount / latest.total_assets) * 100, 2) if latest.total_assets else 0
            target = targets[category]
            status = "in_range"
            gap = 0.0
            if percent < target["min"]:
                status = "below"
                gap = round(target["min"] - percent, 2)
                suggestions.append(f"{CATEGORY_LABELS[category]}低于目标下限 {gap:.2f}% ，后续新增资金可优先补这类资产。")
            elif percent > target["max"]:
                status = "above"
                gap = round(percent - target["max"], 2)
                suggestions.append(f"{CATEGORY_LABELS[category]}高于目标上限 {gap:.2f}% ，后续新增资金可暂停追加。")

            diagnostics[category] = {
                "label": CATEGORY_LABELS[category],
                "amount": amount,
                "percent": percent,
                "target_text": f'{target["min"]:.0f}% - {target["max"]:.0f}%',
                "status": status,
                "gap_percent": gap,
            }

        duplicate_products = [
            holding.product_name
            for holding in latest.holdings
            if holding.category == "fixed_income" and holding.amount / latest.total_assets >= 0.2
        ]
        if len(duplicate_products) >= 2:
            suggestions.append("固收主仓集中在多只大仓位产品，后续可以优先检查是否存在功能重复。")

        return {
            "targets": targets,
            "diagnostics": diagnostics,
            "suggestions": suggestions[:4],
        }

    def get_weekly_attribution(self) -> dict:
        snapshots = self.list_snapshots()
        if not snapshots:
            return {"top_contributors": [], "top_detractors": [], "category_breakdown": {}}

        latest = snapshots[0]
        sorted_holdings = sorted(latest.holdings, key=lambda item: item.weekly_pnl_amount, reverse=True)
        top_contributors = [
            self._holding_contribution_item(holding)
            for holding in sorted_holdings[:3]
        ]
        top_detractors = [
            self._holding_contribution_item(holding)
            for holding in sorted(latest.holdings, key=lambda item: item.weekly_pnl_amount)[:3]
        ]
        category_breakdown: dict[str, float] = defaultdict(float)
        for holding in latest.holdings:
            category_breakdown[holding.category] += holding.weekly_pnl_amount
        category_breakdown = {
            category: round(amount, 2)
            for category, amount in sorted(category_breakdown.items(), key=lambda item: item[1], reverse=True)
        }
        return {
            "top_contributors": top_contributors,
            "top_detractors": top_detractors,
            "category_breakdown": category_breakdown,
        }

    def get_cashflow_analysis(self) -> dict:
        snapshots = self.list_snapshots()
        if len(snapshots) < 2:
            return {
                "available": False,
                "net_flow": 0.0,
                "direction": "none",
                "latest_date": snapshots[0].snapshot_date if snapshots else "",
                "previous_date": "",
                "formula_text": "至少需要两期快照才能推算净资金流。",
            }

        latest = snapshots[0]
        previous = snapshots[1]
        net_flow = round(latest.total_assets - previous.total_assets - latest.weekly_return_amount, 2)
        if net_flow > 0:
            direction = "inflow"
            formula_text = f"较上一期推算净流入 {net_flow:.2f}"
        elif net_flow < 0:
            direction = "outflow"
            formula_text = f"较上一期推算净流出 {abs(net_flow):.2f}"
        else:
            direction = "flat"
            formula_text = "较上一期无明显净资金流"

        return {
            "available": True,
            "net_flow": net_flow,
            "direction": direction,
            "latest_date": latest.snapshot_date,
            "previous_date": previous.snapshot_date,
            "latest_total_assets": latest.total_assets,
            "previous_total_assets": previous.total_assets,
            "weekly_return_amount": latest.weekly_return_amount,
            "formula_text": formula_text,
        }

    def _get_holdings_for_snapshot(self, connection, snapshot_id: int) -> list[HoldingRecord]:
        rows = connection.execute(
            "SELECT * FROM holdings WHERE snapshot_id = ? ORDER BY id ASC",
            (snapshot_id,),
        ).fetchall()
        return [holding_from_row(row) for row in rows]

    def _insert_holding(self, connection, snapshot_id: int, holding: HoldingInput) -> None:
        connection.execute(
            """
            INSERT INTO holdings (
                snapshot_id,
                product_name,
                account_type,
                amount,
                allocation_percent,
                category,
                action,
                weekly_pnl_amount,
                valuation_cutoff_date,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                holding.product_name,
                holding.account_type,
                holding.amount,
                holding.allocation_percent,
                holding.category,
                holding.action,
                holding.weekly_pnl_amount,
                holding.valuation_cutoff_date,
                holding.notes,
            ),
        )

    def _holding_contribution_item(self, holding: HoldingRecord) -> dict:
        return {
            "product_name": holding.product_name,
            "amount": holding.amount,
            "weekly_pnl_amount": holding.weekly_pnl_amount,
            "category": holding.category,
            "label": CATEGORY_LABELS.get(holding.category, holding.category),
        }
