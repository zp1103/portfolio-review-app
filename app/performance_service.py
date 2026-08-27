from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.analytics.classifier import (
    RULE_VERSION,
    candidate_state,
    confirm_candidate_history,
    evidence_strength,
)
from app.analytics.metrics import drawdown_stats, momentum_delta, rank_horizon, streak
from app.analytics.returns import (
    chain_nav,
    compound_return,
    infer_external_flow,
    modified_dietz_return,
    product_period_return,
)
from app.db import Database
from app.product_service import ProductService
from app.service import PortfolioService


def _chart_coordinates(nav_values: list[float]) -> list[tuple[float, float]]:
    if len(nav_values) == 1:
        return [(20.0, 130.0)]
    low, high = min(nav_values), max(nav_values)
    span = high - low
    return [
        (
            20 + index * 960 / (len(nav_values) - 1),
            130.0 if span == 0 else 230 - (nav - low) * 200 / span,
        )
        for index, nav in enumerate(nav_values)
    ]


class PerformanceService:
    def __init__(self, database: Database) -> None:
        self.portfolios = PortfolioService(database)
        self.products = ProductService(database)

    def get_analysis(self) -> dict:
        snapshots = self.portfolios.list_snapshots_chronologically()
        if not snapshots:
            return {
                "rule_version": RULE_VERSION,
                "portfolio": {"available": False, "nav_points": [], "quality": []},
                "active_products": [],
                "comparison": {4: [], 8: [], 12: []},
                "objective_products": [],
                "exited_products": [],
            }

        product_views = self._product_views(snapshots)
        active = [
            item
            for item in product_views
            if item["role"] == "active_watch" and item["lifecycle"] != "exited"
        ]
        objective = [
            item
            for item in product_views
            if item["role"] in {"long_term", "stable"}
            and item["lifecycle"] != "exited"
        ]
        exited = [
            item
            for item in product_views
            if item["lifecycle"] == "exited" and item["role"] != "liquidity"
        ]
        comparison = {
            period: rank_horizon(
                [
                    (
                        f"{item['name']} · {item['account_type']}",
                        item["returns"][period],
                    )
                    for item in active
                ]
            )
            for period in (4, 8, 12)
        }
        return {
            "rule_version": RULE_VERSION,
            "portfolio": self._portfolio_view(snapshots),
            "active_products": active,
            "comparison": comparison,
            "objective_products": objective,
            "exited_products": exited,
        }

    def _portfolio_view(self, snapshots) -> dict:
        period_returns: list[float | None] = []
        flow_rows: list[tuple[float, str]] = []
        quality: list[str] = []
        for index in range(1, len(snapshots)):
            previous, current = snapshots[index - 1], snapshots[index]
            interval = (
                date.fromisoformat(current.snapshot_date)
                - date.fromisoformat(previous.snapshot_date)
            ).days
            if not 5 <= interval <= 9:
                quality.append(f"{current.snapshot_date} 与上期相隔 {interval} 天")

            inferred = infer_external_flow(
                current.total_assets,
                previous.total_assets,
                current.weekly_return_amount,
            )
            flow = (
                current.external_net_flow_amount
                if current.external_net_flow_amount is not None
                else inferred
            )
            source = (
                "confirmed"
                if current.external_flow_confirmed
                and current.external_net_flow_amount is not None
                else "estimated"
            )
            if source == "estimated":
                quality.append(f"{current.snapshot_date} 外部净资金流尚未确认")

            value = modified_dietz_return(
                current.weekly_return_amount,
                previous.total_assets,
                flow,
            )
            if value is None:
                quality.append(f"{current.snapshot_date} 组合收益分母无效")
            period_returns.append(value)
            flow_rows.append((flow, source))

        nav_values = chain_nav(period_returns, 1000)
        valid_nav = [value for value in nav_values if value is not None]
        coordinates = _chart_coordinates(valid_nav)
        nav_points = []
        coordinate_index = 0
        for snapshot, nav in zip(snapshots, nav_values, strict=True):
            point = {"date": snapshot.snapshot_date, "nav": nav}
            if nav is not None:
                point["x"], point["y"] = coordinates[coordinate_index]
                coordinate_index += 1
            nav_points.append(point)

        stats = (
            drawdown_stats(
                valid_nav,
                [
                    point["date"]
                    for point in nav_points
                    if point["nav"] is not None
                ],
            )
            if len(valid_nav) >= 2
            else {}
        )
        latest_flow, latest_source = (
            flow_rows[-1] if flow_rows else (None, "unavailable")
        )
        return {
            "available": len(valid_nav) >= 2,
            "nav_points": nav_points,
            "chart_points": " ".join(
                f"{point['x']:.2f},{point['y']:.2f}"
                for point in nav_points
                if point["nav"] is not None
            ),
            "cumulative_return": (
                valid_nav[-1] / valid_nav[0] - 1
                if len(valid_nav) >= 2
                else None
            ),
            "current_drawdown": stats.get("current_drawdown"),
            "max_drawdown": stats.get("max_drawdown"),
            "high_date": stats.get("high_date"),
            "latest_flow": latest_flow,
            "latest_flow_source": latest_source,
            "quality": quality,
        }

    def _product_views(self, snapshots) -> list[dict]:
        profiles = {
            product.id: product for product in self.products.list_products()
        }
        observations: dict[int, dict[int, object]] = defaultdict(dict)
        for snapshot_index, snapshot in enumerate(snapshots):
            for holding in snapshot.holdings:
                if holding.product_id is not None:
                    observations[holding.product_id][snapshot_index] = holding

        views: list[dict] = []
        for product_id, rows in observations.items():
            product = profiles.get(product_id)
            if product is None or product.management_role == "liquidity":
                continue

            first_index = min(rows)
            end_index = (
                max(rows)
                if product.lifecycle_status == "exited"
                else len(snapshots) - 1
            )
            returns: list[float | None] = []
            return_dates: list[str] = []
            standard_intervals: list[bool] = []
            for index in range(first_index + 1, end_index + 1):
                previous = rows.get(index - 1)
                current = rows.get(index)
                eligible = (
                    previous is not None
                    and current is not None
                    and previous.amount > 0
                )
                value = (
                    product_period_return(
                        current.weekly_pnl_amount,
                        previous.amount,
                        current.transaction_amount,
                        contiguous=True,
                    )
                    if eligible
                    else None
                )
                interval = (
                    date.fromisoformat(snapshots[index].snapshot_date)
                    - date.fromisoformat(snapshots[index - 1].snapshot_date)
                ).days
                returns.append(value)
                return_dates.append(snapshots[index].snapshot_date)
                standard_intervals.append(5 <= interval <= 9)

            last_gap = max(
                (index for index, value in enumerate(returns) if value is None),
                default=-1,
            )
            continuous_returns = returns[last_gap + 1 :]
            continuous_dates = return_dates[last_gap + 1 :]
            continuous_intervals = standard_intervals[last_gap + 1 :]
            base_date_index = first_index + last_gap + 1
            nav_values = chain_nav(continuous_returns, 1000)
            nav_dates = [
                snapshots[base_date_index].snapshot_date,
                *continuous_dates,
            ]
            stats = (
                drawdown_stats(nav_values, nav_dates)
                if len(nav_values) >= 2
                else {}
            )
            windows = {
                period: compound_return(continuous_returns, period)
                for period in (4, 8, 12)
            }
            momentum = momentum_delta(continuous_returns)
            latest_previous = rows.get(end_index - 1)
            latest_current = rows.get(end_index)
            latest_return_was_mathematically_invalid = (
                bool(returns)
                and returns[-1] is None
                and latest_previous is not None
                and latest_current is not None
                and latest_previous.amount > 0
            )
            data_status = (
                "discontinuous"
                if latest_current is None
                else "unavailable"
                if latest_return_was_mathematically_invalid
                else "accumulating"
                if len(continuous_returns) < 4
                else "available"
            )
            view = {
                "id": product.id,
                "name": product.canonical_name,
                "account_type": product.account_type,
                "role": product.management_role,
                "group": product.comparison_group,
                "lifecycle": product.lifecycle_status,
                "returns": windows,
                "current_drawdown": stats.get("current_drawdown"),
                "high_date": stats.get("high_date"),
                "momentum": momentum,
                "streak": streak(continuous_returns),
                "data_status": data_status,
            }

            if (
                product.management_role == "active_watch"
                and len(continuous_returns) >= 8
            ):
                candidates = []
                for end in range(8, len(continuous_returns) + 1):
                    history = continuous_returns[:end]
                    r4 = compound_return(history, 4)
                    r8 = compound_return(history, 8)
                    if r4 is not None and r8 is not None:
                        candidates.append(candidate_state(r4, r8))

                confirmation = confirm_candidate_history(candidates)
                current_candidate = candidates[-1]
                r4, r8 = windows[4], windows[8]
                directional_agreement = (
                    r4 is not None and r8 is not None and r4 * r8 > 0
                )
                supporting_signal = bool(momentum) and (
                    current_candidate.code == "up"
                    and momentum["direction"] == "strengthening"
                    or current_candidate.code == "down"
                    and momentum["direction"] == "weakening"
                    or current_candidate.detail == "weak_to_strong"
                    and momentum["direction"] == "strengthening"
                    or current_candidate.detail == "strong_to_weak"
                    and momentum["direction"] == "weakening"
                )
                view.update(
                    {
                        "candidate_state": confirmation.candidate,
                        "candidate_detail": confirmation.candidate_detail,
                        "confirmed_state": confirmation.confirmed,
                        "confirmed_detail": confirmation.confirmed_detail,
                        "pending": confirmation.pending,
                        "evidence": evidence_strength(
                            confirmed=confirmation.confirmed is not None,
                            periods=len(continuous_returns),
                            directional_agreement=directional_agreement,
                            supporting_signal=supporting_signal,
                            has_quality_issue=False,
                            has_irregular_interval=not all(continuous_intervals),
                        ),
                    }
                )
            views.append(view)
        return views
