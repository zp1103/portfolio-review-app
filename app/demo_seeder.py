from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from app.db import Database
from app.schemas import HoldingInput, SnapshotCreateInput
from app.service import PortfolioService

DEMO_WEEKS = 20

CATEGORY_TEMPLATES = {
    "equity": [
        {
            "product_name": "中证全指指数组合",
            "account_type": "普通账户",
            "base_amount": 150000,
            "category": "equity",
            "action": "hold",
            "exposure_equity_percent": 100,
        },
        {
            "product_name": "科创50指数",
            "account_type": "券商账户",
            "base_amount": 80000,
            "category": "equity",
            "action": "hold",
            "exposure_equity_percent": 100,
        },
        {
            "product_name": "创业板指数基金",
            "account_type": "第三方平台账户",
            "base_amount": 60000,
            "category": "equity",
            "action": "hold",
            "exposure_equity_percent": 100,
        },
    ],
    "fixed_income": [
        {
            "product_name": "全球稳健配置组合",
            "account_type": "第三方平台账户",
            "base_amount": 120000,
            "category": "fixed_income",
            "action": "hold",
            "exposure_equity_percent": 30,
            "exposure_fixed_income_percent": 60,
            "exposure_cash_percent": 10,
        },
        {
            "product_name": "纯债基金A",
            "account_type": "银行理财账户",
            "base_amount": 80000,
            "category": "fixed_income",
            "action": "hold",
            "exposure_fixed_income_percent": 100,
        },
    ],
    "cash": [
        {
            "product_name": "现金账户",
            "account_type": "货币/现金账户",
            "base_amount": 50000,
            "category": "cash",
            "action": "hold",
            "exposure_cash_percent": 100,
        },
    ],
    "gold": [
        {
            "product_name": "黄金ETF",
            "account_type": "券商账户",
            "base_amount": 20000,
            "category": "gold",
            "action": "hold",
            "exposure_gold_percent": 100,
        },
    ],
}


def _generate_weekly_date(weeks_ago: int) -> str:
    today = datetime.now()
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    target_date = last_friday - timedelta(weeks=weeks_ago)
    return target_date.strftime("%Y-%m-%d")


def _generate_holdings(week_index: int, seed: int) -> list[HoldingInput]:
    rng = random.Random(seed + week_index)
    holdings: list[HoldingInput] = []

    for category, templates in CATEGORY_TEMPLATES.items():
        for template in templates:
            variation = rng.uniform(-0.15, 0.15)
            amount = template["base_amount"] * (1 + week_index * 0.005 + variation * 0.5)
            amount = round(amount, 2)

            weekly_pnl_variation = rng.uniform(-0.03, 0.05)
            weekly_pnl = round(amount * weekly_pnl_variation, 2)

            holding = HoldingInput(
                product_name=template["product_name"],
                account_type=template["account_type"],
                amount=amount,
                allocation_percent=0.0,
                category=template["category"],
                action=template["action"],
                weekly_pnl_amount=weekly_pnl,
                valuation_cutoff_date="",
                exposure_equity_percent=template.get("exposure_equity_percent", 0),
                exposure_fixed_income_percent=template.get("exposure_fixed_income_percent", 0),
                exposure_cash_percent=template.get("exposure_cash_percent", 0),
                exposure_gold_percent=template.get("exposure_gold_percent", 0),
                exposure_other_percent=template.get("exposure_other_percent", 0),
                notes="",
            )
            holdings.append(holding)

    total_amount = sum(h.amount for h in holdings)
    for holding in holdings:
        holding.allocation_percent = round((holding.amount / total_amount) * 100, 2) if total_amount > 0 else 0

    return holdings


def _should_seed() -> bool:
    env_value = os.environ.get("SEED_DEMO_DATA", "").lower()
    return env_value in ("true", "1", "yes")


def seed_demo_data_if_needed(database: Database) -> bool:
    if not _should_seed():
        return False

    if database.has_snapshots():
        return False

    service = PortfolioService(database)
    seed = int(os.environ.get("DEMO_SEED", "42"))

    for week_ago in range(DEMO_WEEKS - 1, -1, -1):
        snapshot_date = _generate_weekly_date(week_ago)
        holdings = _generate_holdings(week_ago, seed)

        total_assets = round(sum(h.amount for h in holdings), 2)
        cash_balance = round(sum(h.amount for h in holdings if h.category == "cash"), 2)
        weekly_return_amount = round(sum(h.weekly_pnl_amount for h in holdings), 2)

        ytd_variation = random.Random(seed + week_ago + 100).uniform(0.02, 0.15)
        ytd_return_amount = round(total_assets * ytd_variation, 2)

        payload = SnapshotCreateInput(
            snapshot_date=snapshot_date,
            total_assets=total_assets,
            cash_balance=cash_balance,
            weekly_return_amount=weekly_return_amount,
            ytd_return_amount=ytd_return_amount,
            data_cutoff_notes="演示数据",
            notes="",
            holdings=holdings,
        )
        service.create_snapshot(payload)

    return True
