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
        self.database = Database(self.temp_dir / "portfolio.db")
        self.database.initialize()
        self.service = PortfolioService(self.database)

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_quality_checks_unavailable_when_no_snapshots(self) -> None:
        checks = self.service.get_data_quality_checks()

        self.assertFalse(checks["available"])
        self.assertEqual(checks["issues"], [])

    def test_reports_unmapped_product_and_unconfirmed_flow(self) -> None:
        for snapshot_date, amount, pnl in (
            ("2026-08-14", 100000, 0),
            ("2026-08-21", 101000, 1000),
        ):
            self.service.create_snapshot(
                SnapshotCreateInput(
                    snapshot_date=snapshot_date,
                    total_assets=amount,
                    cash_balance=0,
                    weekly_return_amount=pnl,
                    external_net_flow_amount=0,
                    external_flow_confirmed=False,
                    holdings=[
                        HoldingInput(
                            product_name="科创50",
                            account_type="普通账户",
                            amount=amount,
                            allocation_percent=100,
                            category="equity",
                            weekly_pnl_amount=pnl,
                        )
                    ],
                )
            )
        with self.database.session() as connection:
            connection.execute(
                "UPDATE holdings SET product_id = NULL WHERE snapshot_id = "
                "(SELECT id FROM weekly_snapshots "
                "ORDER BY snapshot_date DESC LIMIT 1)"
            )
            connection.execute(
                "UPDATE weekly_snapshots SET external_flow_confirmed = 0 "
                "WHERE snapshot_date = '2026-08-21'"
            )

        issues = self.service.get_data_quality_checks()["issues"]
        issues_by_type = {issue["type"]: issue for issue in issues}

        self.assertIn("product_unmapped", issues_by_type)
        self.assertIn("external_flow_unconfirmed", issues_by_type)
        self.assertEqual(issues_by_type["product_unmapped"]["severity"], "warning")
        self.assertEqual(
            issues_by_type["product_unmapped"]["details"],
            {"product_name": "科创50"},
        )
        self.assertEqual(
            issues_by_type["external_flow_unconfirmed"]["severity"],
            "info",
        )
        self.assertEqual(
            issues_by_type["external_flow_unconfirmed"]["details"],
            {"snapshot_date": "2026-08-21"},
        )

    def test_confirmed_flag_without_amount_is_still_estimated_and_unconfirmed(
        self,
    ) -> None:
        for snapshot_date, amount, pnl in (
            ("2026-08-14", 100000, 0),
            ("2026-08-21", 105000, 1000),
        ):
            self.service.create_snapshot(SnapshotCreateInput(
                snapshot_date=snapshot_date,
                total_assets=amount,
                cash_balance=amount,
                weekly_return_amount=pnl,
                external_net_flow_amount=None,
                external_flow_confirmed=True,
                holdings=[HoldingInput(
                    product_name="现金",
                    account_type="货币/现金账户",
                    amount=amount,
                    allocation_percent=100,
                    category="cash",
                )],
            ))

        cashflow = self.service.get_cashflow_analysis()
        issue_types = {
            issue["type"]
            for issue in self.service.get_data_quality_checks()["issues"]
        }

        self.assertEqual(cashflow["net_flow"], 4000)
        self.assertEqual(cashflow["source"], "estimated")
        self.assertIn("external_flow_unconfirmed", issue_types)

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

    def test_quality_checks_detects_invalid_implied_cost(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=50000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="科创50",
                        account_type="普通账户",
                        amount=50000,
                        allocation_percent=16.67,
                        category="equity",
                        cumulative_pnl_amount=52000,
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=200000,
                        allocation_percent=66.67,
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
        implied_cost_issues = [i for i in checks["issues"] if i["type"] == "implied_cost_invalid"]
        self.assertEqual(len(implied_cost_issues), 1)
        self.assertIn("推导成本异常", implied_cost_issues[0]["message"])
        self.assertEqual(implied_cost_issues[0]["details"]["product_name"], "科创50")
        self.assertEqual(implied_cost_issues[0]["details"]["implied_cost"], -2000)

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
        self.database = Database(self.temp_dir / "portfolio.db")
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

    def test_dashboard_shows_unmapped_product_and_unconfirmed_flow_details(self) -> None:
        for snapshot_date, amount, pnl in (
            ("2026-08-14", 100000, 0),
            ("2026-08-21", 101000, 1000),
        ):
            created = self.client.post(
                "/api/weekly-snapshots",
                json={
                    "snapshot_date": snapshot_date,
                    "total_assets": amount,
                    "cash_balance": 0,
                    "weekly_return_amount": pnl,
                    "external_net_flow_amount": 0,
                    "external_flow_confirmed": True,
                    "holdings": [
                        {
                            "product_name": "科创50",
                            "account_type": "普通账户",
                            "amount": amount,
                            "allocation_percent": 100,
                            "category": "equity",
                            "weekly_pnl_amount": pnl,
                        }
                    ],
                },
            )
            self.assertEqual(created.status_code, 201)
        with self.database.session() as connection:
            connection.execute(
                "UPDATE holdings SET product_id = NULL WHERE snapshot_id = "
                "(SELECT id FROM weekly_snapshots "
                "ORDER BY snapshot_date DESC LIMIT 1)"
            )
            connection.execute(
                "UPDATE weekly_snapshots SET external_flow_confirmed = 0 "
                "WHERE snapshot_date = '2026-08-21'"
            )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("尚未绑定产品档案", response.text)
        self.assertIn("持仓：<strong>科创50</strong>", response.text)
        self.assertIn("本期外部净资金流仍为系统估算", response.text)
        self.assertIn("快照日期：<strong>2026-08-21</strong>", response.text)

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
