import shutil
import unittest
from pathlib import Path

from app.db import Database
from app.schemas import HoldingInput, SnapshotCreateInput
from app.service import PortfolioService


class PortfolioServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(__file__).resolve().parent / "_tmp_service"
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        database = Database(self.temp_dir / "portfolio.db")
        database.initialize()
        self.service = PortfolioService(database)

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_create_and_list_snapshot_with_holdings(self) -> None:
        created = self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=421000,
                cash_balance=80000,
                weekly_return_amount=-3200,
                ytd_return_amount=8600,
                data_cutoff_notes="普通账户到周五，第三方到账周四，养老金到账周三",
                notes="First weekly review",
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=45000,
                        allocation_percent=10.69,
                        category="equity",
                        action="hold",
                        weekly_pnl_amount=1200,
                        valuation_cutoff_date="2026-04-18",
                        notes="维持核心仓",
                    ),
                    HoldingInput(
                        product_name="科创50",
                        account_type="普通账户",
                        amount=10000,
                        allocation_percent=2.38,
                        category="equity",
                        action="buy",
                        weekly_pnl_amount=-260,
                        valuation_cutoff_date="2026-04-18",
                        notes="新增试探仓",
                    ),
                ],
            )
        )

        self.assertIsNotNone(created.id)
        self.assertEqual(created.snapshot_date, "2026-04-18")
        self.assertEqual(len(created.holdings), 2)
        self.assertEqual(created.holdings[0].weekly_pnl_amount, 1200)
        self.assertEqual(created.holdings[0].valuation_cutoff_date, "2026-04-18")

        snapshots = self.service.list_snapshots()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].total_assets, 421000)
        self.assertEqual(
            {holding.product_name for holding in snapshots[0].holdings},
            {"中证全指指数组合", "科创50"},
        )

    def test_allocation_summary_groups_holdings_by_category(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=60000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                        weekly_pnl_amount=1800,
                        valuation_cutoff_date="2026-04-18",
                    ),
                    HoldingInput(
                        product_name="全球稳健组合",
                        account_type="普通账户",
                        amount=90000,
                        allocation_percent=30,
                        category="fixed_income",
                        weekly_pnl_amount=320,
                        valuation_cutoff_date="2026-04-17",
                    ),
                    HoldingInput(
                        product_name="现金",
                        account_type="现金",
                        amount=60000,
                        allocation_percent=20,
                        category="cash",
                        weekly_pnl_amount=0,
                        valuation_cutoff_date="2026-04-18",
                    ),
                ],
            )
        )

        summary = self.service.get_allocation_summary()

        self.assertEqual(summary.total_assets, 300000)
        self.assertEqual(summary.categories["equity"].amount, 120000)
        self.assertEqual(summary.categories["fixed_income"].amount, 90000)
        self.assertEqual(summary.categories["cash"].amount, 60000)

    def test_update_snapshot_replaces_holdings(self) -> None:
        created = self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=300000,
                cash_balance=60000,
                weekly_return_amount=1200,
                ytd_return_amount=6400,
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=40,
                        category="equity",
                        weekly_pnl_amount=1800,
                        valuation_cutoff_date="2026-04-18",
                    ),
                ],
            )
        )

        updated = self.service.update_snapshot(
            created.id,
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=305000,
                cash_balance=55000,
                weekly_return_amount=1800,
                ytd_return_amount=7000,
                data_cutoff_notes="统一按周三口径",
                notes="补充第二条持仓",
                holdings=[
                    HoldingInput(
                        product_name="中证全指指数组合",
                        account_type="普通账户",
                        amount=120000,
                        allocation_percent=39.34,
                        category="equity",
                        weekly_pnl_amount=2100,
                        valuation_cutoff_date="2026-04-18",
                    ),
                    HoldingInput(
                        product_name="全球稳健配置组合",
                        account_type="第三方平台账户",
                        amount=100000,
                        allocation_percent=32.79,
                        category="fixed_income",
                        weekly_pnl_amount=-340,
                        valuation_cutoff_date="2026-04-17",
                    ),
                ],
            ),
        )

        self.assertEqual(updated.total_assets, 305000)
        self.assertEqual(len(updated.holdings), 2)
        self.assertEqual(updated.holdings[1].product_name, "全球稳健配置组合")
        self.assertEqual(updated.holdings[1].weekly_pnl_amount, -340)
        self.assertEqual(updated.holdings[1].valuation_cutoff_date, "2026-04-17")

    def test_target_allocation_can_be_saved_and_read_back(self) -> None:
        updated = self.service.update_target_allocation(
            {
                "equity": {"min": 50, "max": 60},
                "fixed_income": {"min": 25, "max": 35},
                "cash": {"min": 5, "max": 10},
                "gold": {"min": 0, "max": 5},
            }
        )

        self.assertEqual(updated["equity"]["min"], 50)
        self.assertEqual(updated["equity"]["max"], 60)
        self.assertEqual(updated["fixed_income"]["min"], 25)
        self.assertEqual(updated["cash"]["max"], 10)

    def test_portfolio_analysis_flags_categories_against_targets(self) -> None:
        self.service.update_target_allocation(
            {
                "equity": {"min": 50, "max": 60},
                "fixed_income": {"min": 25, "max": 35},
                "cash": {"min": 5, "max": 10},
                "gold": {"min": 0, "max": 5},
            }
        )
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=400000,
                cash_balance=30000,
                weekly_return_amount=2100,
                ytd_return_amount=9800,
                holdings=[
                    HoldingInput(
                        product_name="中证全指",
                        account_type="普通账户",
                        amount=160000,
                        allocation_percent=40,
                        category="equity",
                        weekly_pnl_amount=3000,
                        valuation_cutoff_date="2026-04-18",
                    ),
                    HoldingInput(
                        product_name="稳健组合",
                        account_type="第三方平台账户",
                        amount=200000,
                        allocation_percent=50,
                        category="fixed_income",
                        weekly_pnl_amount=-600,
                        valuation_cutoff_date="2026-04-17",
                    ),
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=40000,
                        allocation_percent=10,
                        category="cash",
                        weekly_pnl_amount=0,
                        valuation_cutoff_date="2026-04-18",
                    ),
                ],
            )
        )

        analysis = self.service.get_portfolio_analysis()

        self.assertEqual(analysis["diagnostics"]["equity"]["status"], "below")
        self.assertEqual(analysis["diagnostics"]["fixed_income"]["status"], "above")
        self.assertEqual(analysis["diagnostics"]["cash"]["status"], "in_range")
        self.assertTrue(any("权益低于目标下限" in item for item in analysis["suggestions"]))

    def test_weekly_attribution_returns_top_and_bottom_contributors(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=420000,
                cash_balance=30000,
                weekly_return_amount=2400,
                ytd_return_amount=9800,
                holdings=[
                    HoldingInput(
                        product_name="中证全指",
                        account_type="普通账户",
                        amount=160000,
                        allocation_percent=38.1,
                        category="equity",
                        weekly_pnl_amount=3200,
                        valuation_cutoff_date="2026-04-18",
                    ),
                    HoldingInput(
                        product_name="科创50",
                        account_type="普通账户",
                        amount=50000,
                        allocation_percent=11.9,
                        category="equity",
                        weekly_pnl_amount=1800,
                        valuation_cutoff_date="2026-04-17",
                    ),
                    HoldingInput(
                        product_name="全球稳健配置组合",
                        account_type="第三方平台账户",
                        amount=100000,
                        allocation_percent=23.81,
                        category="fixed_income",
                        weekly_pnl_amount=-420,
                        valuation_cutoff_date="2026-04-16",
                    ),
                    HoldingInput(
                        product_name="博时恒泽混合C",
                        account_type="普通账户",
                        amount=80000,
                        allocation_percent=19.05,
                        category="fixed_income",
                        weekly_pnl_amount=-160,
                        valuation_cutoff_date="2026-04-17",
                    ),
                ],
            )
        )

        attribution = self.service.get_weekly_attribution()

        self.assertEqual(attribution["top_contributors"][0]["product_name"], "中证全指")
        self.assertEqual(attribution["top_contributors"][1]["product_name"], "科创50")
        self.assertEqual(attribution["top_detractors"][0]["product_name"], "全球稳健配置组合")
        self.assertEqual(attribution["category_breakdown"]["equity"], 5000)

    def test_cashflow_analysis_derives_net_flow_from_two_snapshots(self) -> None:
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-11",
                total_assets=400000,
                cash_balance=30000,
                weekly_return_amount=2000,
                holdings=[
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=30000,
                        allocation_percent=7.5,
                        category="cash",
                    )
                ],
            )
        )
        self.service.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-04-18",
                total_assets=419000,
                cash_balance=35000,
                weekly_return_amount=7000,
                holdings=[
                    HoldingInput(
                        product_name="现金账户",
                        account_type="货币/现金账户",
                        amount=35000,
                        allocation_percent=8.35,
                        category="cash",
                    )
                ],
            )
        )

        cashflow = self.service.get_cashflow_analysis()

        self.assertTrue(cashflow["available"])
        self.assertEqual(cashflow["net_flow"], 12000)
        self.assertEqual(cashflow["direction"], "inflow")
        self.assertIn("净流入 12000.00", cashflow["formula_text"])


if __name__ == "__main__":
    unittest.main()
