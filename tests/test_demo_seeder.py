import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db import Database
from app.demo_seeder import DEMO_WEEKS, seed_demo_data_if_needed
from app.schemas import HoldingInput, SnapshotCreateInput
from app.service import PortfolioService


class DemoSeederTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(__file__).resolve().parent / "_tmp_seeder"
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "portfolio.db"

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_seed_demo_data_creates_20_weekly_snapshots(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "true"}):
            result = seed_demo_data_if_needed(database)

        self.assertTrue(result)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()

        self.assertEqual(len(snapshots), DEMO_WEEKS)

    def test_seed_demo_data_includes_all_categories(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "true"}):
            seed_demo_data_if_needed(database)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()
        latest = snapshots[0]

        categories = {h.category for h in latest.holdings}

        self.assertIn("equity", categories)
        self.assertIn("fixed_income", categories)
        self.assertIn("cash", categories)
        self.assertIn("gold", categories)

    def test_seed_demo_data_not_called_when_env_false(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "false"}):
            result = seed_demo_data_if_needed(database)

        self.assertFalse(result)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()
        self.assertEqual(len(snapshots), 0)

    def test_seed_demo_data_not_called_when_env_missing(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        result = seed_demo_data_if_needed(database)

        self.assertFalse(result)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()
        self.assertEqual(len(snapshots), 0)

    def test_seed_demo_data_not_called_when_existing_snapshots(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        service = PortfolioService(database)
        service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=100000,
                cash_balance=10000,
                weekly_return_amount=0,
                ytd_return_amount=0,
                holdings=[
                    HoldingInput(
                        product_name="测试持仓",
                        account_type="普通账户",
                        amount=10000,
                        allocation_percent=10,
                        category="equity",
                    )
                ],
            )
        )

        snapshots_before = service.list_snapshots()
        self.assertEqual(len(snapshots_before), 1)

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "true"}):
            result = seed_demo_data_if_needed(database)

        self.assertFalse(result)

        snapshots_after = service.list_snapshots()
        self.assertEqual(len(snapshots_after), 1)
        self.assertEqual(snapshots_after[0].holdings[0].product_name, "测试持仓")

    def test_seed_demo_data_snapshots_have_valid_dates(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "true"}):
            seed_demo_data_if_needed(database)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()

        dates = [s.snapshot_date for s in snapshots]
        unique_dates = set(dates)

        self.assertEqual(len(unique_dates), DEMO_WEEKS)

        for date in dates:
            self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")

    def test_seed_demo_data_snapshots_sorted_descending(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "true"}):
            seed_demo_data_if_needed(database)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()

        for i in range(len(snapshots) - 1):
            self.assertGreater(snapshots[i].snapshot_date, snapshots[i + 1].snapshot_date)

    def test_seed_demo_data_holdings_have_exposure_settings(self) -> None:
        database = Database(self.db_path)
        database.initialize()

        with patch.dict(os.environ, {"SEED_DEMO_DATA": "true"}):
            seed_demo_data_if_needed(database)

        service = PortfolioService(database)
        snapshots = service.list_snapshots()
        latest = snapshots[0]

        fixed_income_holdings = [h for h in latest.holdings if h.category == "fixed_income"]
        self.assertTrue(len(fixed_income_holdings) > 0)

        mixed_holding = next((h for h in fixed_income_holdings if h.exposure_equity_percent > 0), None)
        self.assertIsNotNone(mixed_holding)
        self.assertEqual(mixed_holding.exposure_fixed_income_percent, 60)
        self.assertEqual(mixed_holding.exposure_equity_percent, 30)


if __name__ == "__main__":
    unittest.main()
