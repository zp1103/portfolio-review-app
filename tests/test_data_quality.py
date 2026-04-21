import shutil
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.schemas import HoldingInput, SnapshotCreateInput
from app.service import PortfolioService


class DataQualityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(__file__).resolve().parent / "_tmp_quality"
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        database = Database(self.temp_dir / "portfolio.db")
        database.initialize()
        self.service = PortfolioService(database)

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_quality_checks_unavailable_when_no_snapshots(self) -> None:
        checks = self.service.get_data_quality_checks()

        self.assertFalse(checks["available"])
        self.assertEqual(checks["issues"], [])

    def test_quality_checks_passed_with_valid_data(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=50000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=130000,
                        allocation_percent=43.33,
                        category="fixed_income",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        self.assertEqual(checks["issues"], [])

    def test_quality_checks_detects_total_assets_mismatch(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=400000,
                cash_balance=50000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=130000,
                        allocation_percent=43.33,
                        category="fixed_income",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        mismatch_issues = [i for i in checks["issues"] if i["type"] == "total_assets_mismatch"]
        self.assertEqual(len(mismatch_issues), 1)
        self.assertEqual(mismatch_issues[0]["severity"], "warning")
        self.assertIn("总资产与持仓金额合计不一致", mismatch_issues[0]["message"])
        self.assertEqual(mismatch_issues[0]["details"]["snapshot_total"], 400000)
        self.assertEqual(mismatch_issues[0]["details"]["holdings_sum"], 300000)
        self.assertEqual(mismatch_issues[0]["details"]["difference"], 100000)

    def test_quality_checks_detects_cash_balance_mismatch(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=30000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=130000,
                        allocation_percent=43.33,
                        category="fixed_income",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        cash_issues = [i for i in checks["issues"] if i["type"] == "cash_balance_mismatch"]
        self.assertEqual(len(cash_issues), 1)
        self.assertEqual(cash_issues[0]["severity"], "warning")
        self.assertIn("现金余额与现金类持仓金额不一致", cash_issues[0]["message"])
        self.assertEqual(cash_issues[0]["details"]["snapshot_cash"], 30000)
        self.assertEqual(cash_issues[0]["details"]["cash_holdings_sum"], 50000)
        self.assertEqual(cash_issues[0]["details"]["difference"], -20000)

    def test_quality_checks_detects_exposure_sum_invalid(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=50000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="全球稳健配置组合",
                        account_type="第三方平台账户",
                        amount=100000,
                        allocation_percent=33.33,
                        category="fixed_income",
                        exposure_equity_percent=30,
                        exposure_fixed_income_percent=50,
                        exposure_cash_percent=10,
                    ),
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=150000,
                        allocation_percent=50,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        exposure_issues = [i for i in checks["issues"] if i["type"] == "exposure_sum_invalid"]
        self.assertEqual(len(exposure_issues), 1)
        self.assertEqual(exposure_issues[0]["severity"], "warning")
        self.assertIn("穿透比例合计异常", exposure_issues[0]["message"])
        self.assertIn("全球稳健配置组合", exposure_issues[0]["message"])
        self.assertEqual(exposure_issues[0]["details"]["product_name"], "全球稳健配置组合")
        self.assertEqual(exposure_issues[0]["details"]["exposure_sum"], 90)
        self.assertEqual(exposure_issues[0]["details"]["expected"], 100)

    def test_quality_checks_ignores_zero_exposure_sum(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=50000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=130000,
                        allocation_percent=43.33,
                        category="fixed_income",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        exposure_issues = [i for i in checks["issues"] if i["type"] == "exposure_sum_invalid"]
        self.assertEqual(len(exposure_issues), 0)

    def test_quality_checks_detects_multiple_issues(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=400000,
                cash_balance=30000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="全球稳健配置组合",
                        account_type="第三方平台账户",
                        amount=100000,
                        allocation_percent=25,
                        category="fixed_income",
                        exposure_equity_percent=30,
                        exposure_fixed_income_percent=50,
                        exposure_cash_percent=10,
                    ),
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=30,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=12.5,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        self.assertEqual(len(checks["issues"]), 3)

        issue_types = {i["type"] for i in checks["issues"]}
        self.assertIn("total_assets_mismatch", issue_types)
        self.assertIn("cash_balance_mismatch", issue_types)
        self.assertIn("exposure_sum_invalid", issue_types)

    def test_quality_checks_allows_tiny_floating_point_difference(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000.001,
                cash_balance=50000.001,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=130000,
                        allocation_percent=43.33,
                        category="fixed_income",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="cash",
                    ),
                ],
            )
        )

        checks = self.service.get_data_quality_checks()

        self.assertTrue(checks["available"])
        self.assertEqual(len(checks["issues"]), 0)


class DataQualityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(__file__).resolve().parent / "_tmp_api_quality"
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.client = TestClient(create_app(self.temp_dir / "portfolio.db"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_dashboard_works_without_quality_issues(self) -> None:
        self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 300000,
                "cash_balance": 50000,
                "weekly_return_amount": 1200,
                "ytd_return_amount": 6400,
                "holdings": [
                    {
                        "product_name": "中证全指指数组合",
                        "account_type": "普通账户",
                        "amount": 120000,
                        "allocation_percent": 40,
                        "category": "equity",
                    },
                    {
                        "product_name": "全球稳健组合",
                        "account_type": "普通账户",
                        "amount": 130000,
                        "allocation_percent": 43.33,
                        "category": "fixed_income",
                    },
                    {
                        "product_name": "现金账户",
                        "account_type": "货币/现金账户",
                        "amount": 50000,
                        "allocation_percent": 16.67,
                        "category": "cash",
                    },
                ],
            },
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("数据质量提示", response.text)

    def test_dashboard_shows_quality_warning_with_issues(self) -> None:
        self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 400000,
                "cash_balance": 30000,
                "weekly_return_amount": 1200,
                "ytd_return_amount": 6400,
                "holdings": [
                    {
                        "product_name": "全球稳健配置组合",
                        "account_type": "第三方平台账户",
                        "amount": 100000,
                        "allocation_percent": 25,
                        "category": "fixed_income",
                        "exposure_equity_percent": 30,
                        "exposure_fixed_income_percent": 50,
                        "exposure_cash_percent": 10,
                    },
                    {
                        "product_name": "中证全指指数组合",
                        "account_type": "普通账户",
                        "amount": 120000,
                        "allocation_percent": 30,
                        "category": "equity",
                    },
                    {
                        "product_name": "现金账户",
                        "account_type": "货币/现金账户",
                        "amount": 50000,
                        "allocation_percent": 12.5,
                        "category": "cash",
                    },
                ],
            },
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("数据质量提示", response.text)
        self.assertIn("总资产与持仓金额合计不一致", response.text)
        self.assertIn("现金余额与现金类持仓金额不一致", response.text)
        self.assertIn("穿透比例合计异常", response.text)

    def test_saving_still_works_with_quality_issues(self) -> None:
        first_response = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-11",
                "total_assets": 300000,
                "cash_balance": 50000,
                "weekly_return_amount": 1200,
                "ytd_return_amount": 6400,
                "holdings": [
                    {
                        "product_name": "中证全指指数组合",
                        "account_type": "普通账户",
                        "amount": 250000,
                        "allocation_percent": 83.33,
                        "category": "equity",
                    },
                    {
                        "product_name": "现金账户",
                        "account_type": "货币/现金账户",
                        "amount": 50000,
                        "allocation_percent": 16.67,
                        "category": "cash",
                    },
                ],
            },
        )
        self.assertEqual(first_response.status_code, 201)

        second_response = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 400000,
                "cash_balance": 30000,
                "weekly_return_amount": 2000,
                "ytd_return_amount": 8400,
                "holdings": [
                    {
                        "product_name": "全球稳健配置组合",
                        "account_type": "第三方平台账户",
                        "amount": 100000,
                        "allocation_percent": 25,
                        "category": "fixed_income",
                        "exposure_equity_percent": 30,
                        "exposure_fixed_income_percent": 50,
                        "exposure_cash_percent": 10,
                    },
                    {
                        "product_name": "现金账户",
                        "account_type": "货币/现金账户",
                        "amount": 50000,
                        "allocation_percent": 12.5,
                        "category": "cash",
                    },
                ],
            },
        )
        self.assertEqual(second_response.status_code, 201)

        list_response = self.client.get("/api/weekly-snapshots")
        snapshots = list_response.json()
        self.assertEqual(len(snapshots), 2)


if __name__ == "__main__":
    unittest.main()
