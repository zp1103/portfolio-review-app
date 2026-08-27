import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.db import Database
from app.performance_service import PerformanceService
from app.product_service import ProductService
from app.schemas import HoldingInput, ProductUpdateInput, SnapshotCreateInput
from app.service import PortfolioService


class PerformanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "portfolio.db")
        self.database.initialize()
        self.portfolios = PortfolioService(self.database)
        self.products = ProductService(self.database)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def add_snapshot(self, index: int, amount: float, pnl: float = 1000) -> None:
        self.portfolios.create_snapshot(
            SnapshotCreateInput(
                snapshot_date=str(date(2026, 5, 1) + timedelta(days=7 * index)),
                total_assets=amount,
                cash_balance=0,
                weekly_return_amount=pnl,
                external_net_flow_amount=0,
                external_flow_confirmed=True,
                holdings=[
                    HoldingInput(
                        product_name="观察宽基",
                        account_type="普通账户",
                        amount=amount,
                        allocation_percent=100,
                        category="equity",
                        transaction_amount=0,
                        weekly_pnl_amount=pnl,
                        management_role="active_watch",
                        comparison_group="broad",
                    )
                ],
            )
        )

    def test_builds_portfolio_and_active_product_metrics(self) -> None:
        for index in range(13):
            self.add_snapshot(index, 100000 + index * 1000)

        result = PerformanceService(self.database).get_analysis()

        self.assertEqual(result["rule_version"], "trend-v1")
        self.assertTrue(result["portfolio"]["available"])
        self.assertEqual(result["portfolio"]["nav_points"][0]["nav"], 1000)
        self.assertEqual(len(result["active_products"]), 1)
        self.assertIsNotNone(result["active_products"][0]["returns"][12])
        self.assertIn(
            result["active_products"][0]["confirmed_state"],
            {"up", "sideways"},
        )

    def test_long_term_has_metrics_but_no_state(self) -> None:
        for index in range(9):
            self.add_snapshot(index, 100000 + index * 1000)
        product = self.products.list_products()[0]
        self.products.update_product(
            product.id,
            ProductUpdateInput(
                management_role="long_term",
                comparison_group="broad",
                lifecycle_status="active",
            ),
        )

        result = PerformanceService(self.database).get_analysis()

        self.assertEqual(result["active_products"], [])
        self.assertEqual(len(result["objective_products"]), 1)
        self.assertNotIn("confirmed_state", result["objective_products"][0])

    def test_exited_product_keeps_history_and_leaves_ranking(self) -> None:
        for index in range(9):
            self.add_snapshot(index, 100000 + index * 1000)
        product = self.products.list_products()[0]
        self.products.update_product(
            product.id,
            ProductUpdateInput(
                management_role="active_watch",
                comparison_group="broad",
                lifecycle_status="exited",
            ),
        )

        result = PerformanceService(self.database).get_analysis()

        self.assertEqual(result["active_products"], [])
        self.assertEqual(len(result["exited_products"]), 1)

    def test_missing_product_period_breaks_window(self) -> None:
        for index in range(8):
            self.add_snapshot(index, 100000 + index * 1000)
        self.portfolios.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-07-03",
                total_assets=10000,
                cash_balance=10000,
                weekly_return_amount=0,
                holdings=[
                    HoldingInput(
                        product_name="现金",
                        account_type="货币/现金账户",
                        amount=10000,
                        allocation_percent=100,
                        category="cash",
                    )
                ],
            )
        )

        result = PerformanceService(self.database).get_analysis()
        product = next(
            item
            for item in result["active_products"]
            if item["name"] == "观察宽基"
        )

        self.assertIsNone(product["returns"][8])
        self.assertEqual(product["data_status"], "discontinuous")

    def test_irregular_interval_caps_evidence(self) -> None:
        for index in range(13):
            self.add_snapshot(index, 100000 + index * 1000)
        with self.database.session() as connection:
            connection.execute(
                "UPDATE weekly_snapshots SET snapshot_date = '2026-06-17' "
                "WHERE snapshot_date = '2026-06-12'"
            )

        product = PerformanceService(self.database).get_analysis()[
            "active_products"
        ][0]

        self.assertNotEqual(product["evidence"], "high")

    def test_exit_period_is_calculated_but_reentry_starts_new_segment(self) -> None:
        for index in range(9):
            self.add_snapshot(index, 100000 + index * 1000)
        self.portfolios.create_snapshot(
            SnapshotCreateInput(
                snapshot_date="2026-07-03",
                total_assets=10000,
                cash_balance=10000,
                weekly_return_amount=500,
                external_net_flow_amount=-98500,
                external_flow_confirmed=True,
                holdings=[
                    HoldingInput(
                        product_name="观察宽基",
                        account_type="普通账户",
                        amount=0,
                        allocation_percent=0,
                        category="equity",
                        transaction_amount=-108000,
                        weekly_pnl_amount=500,
                    ),
                    HoldingInput(
                        product_name="现金",
                        account_type="货币/现金账户",
                        amount=10000,
                        allocation_percent=100,
                        category="cash",
                    ),
                ],
            )
        )

        before_gap = PerformanceService(self.database).get_analysis()[
            "active_products"
        ][0]
        self.assertIsNotNone(before_gap["returns"][8])

        for snapshot_date, include_product in (
            ("2026-07-10", False),
            ("2026-07-17", True),
        ):
            holdings = [
                HoldingInput(
                    product_name="现金",
                    account_type="货币/现金账户",
                    amount=10000,
                    allocation_percent=50 if include_product else 100,
                    category="cash",
                )
            ]
            if include_product:
                holdings.append(
                    HoldingInput(
                        product_name="观察宽基",
                        account_type="普通账户",
                        amount=10000,
                        allocation_percent=50,
                        category="equity",
                        transaction_amount=10000,
                        weekly_pnl_amount=0,
                    )
                )
            self.portfolios.create_snapshot(
                SnapshotCreateInput(
                    snapshot_date=snapshot_date,
                    total_assets=sum(item.amount for item in holdings),
                    cash_balance=10000,
                    weekly_return_amount=0,
                    external_net_flow_amount=0,
                    external_flow_confirmed=True,
                    holdings=holdings,
                )
            )

        after_reentry = PerformanceService(self.database).get_analysis()[
            "active_products"
        ][0]
        self.assertIsNone(after_reentry["returns"][4])
        self.assertEqual(after_reentry["data_status"], "accumulating")

    def test_reentry_after_zero_balance_is_accumulating(self) -> None:
        for snapshot_date, product_amount, transaction_amount in (
            ("2026-05-01", 10000, 0),
            ("2026-05-08", 0, -10000),
            ("2026-05-15", 10000, 10000),
        ):
            cash_amount = 10000
            total_assets = product_amount + cash_amount
            self.portfolios.create_snapshot(
                SnapshotCreateInput(
                    snapshot_date=snapshot_date,
                    total_assets=total_assets,
                    cash_balance=cash_amount,
                    external_net_flow_amount=0,
                    external_flow_confirmed=True,
                    holdings=[
                        HoldingInput(
                            product_name="观察宽基",
                            account_type="普通账户",
                            amount=product_amount,
                            allocation_percent=product_amount / total_assets * 100,
                            category="equity",
                            transaction_amount=transaction_amount,
                        ),
                        HoldingInput(
                            product_name="现金",
                            account_type="货币/现金账户",
                            amount=cash_amount,
                            allocation_percent=cash_amount / total_assets * 100,
                            category="cash",
                        ),
                    ],
                )
            )

        product = PerformanceService(self.database).get_analysis()[
            "active_products"
        ][0]

        self.assertIsNone(product["returns"][4])
        self.assertEqual(product["data_status"], "accumulating")

    def test_portfolio_nav_does_not_resume_after_invalid_period(self) -> None:
        for snapshot_date, total_assets, pnl, flow in (
            ("2026-05-01", 100, 0, 0),
            ("2026-05-08", 1, 1, -200),
            ("2026-05-15", 2, 1, 0),
        ):
            self.portfolios.create_snapshot(
                SnapshotCreateInput(
                    snapshot_date=snapshot_date,
                    total_assets=total_assets,
                    cash_balance=total_assets,
                    weekly_return_amount=pnl,
                    external_net_flow_amount=flow,
                    external_flow_confirmed=True,
                    holdings=[
                        HoldingInput(
                            product_name="现金",
                            account_type="货币/现金账户",
                            amount=total_assets,
                            allocation_percent=100,
                            category="cash",
                        )
                    ],
                )
            )

        portfolio = PerformanceService(self.database).get_analysis()["portfolio"]

        self.assertEqual(
            [point["nav"] for point in portfolio["nav_points"]],
            [1000, None, None],
        )
        self.assertFalse(portfolio["available"])
        self.assertIsNone(portfolio["current_drawdown"])

    def test_exited_product_ends_at_its_last_observation(self) -> None:
        for index in range(5):
            self.add_snapshot(index, 100000 + index * 1000)
        product = self.products.list_products()[0]
        self.products.update_product(
            product.id,
            ProductUpdateInput(
                management_role="active_watch",
                comparison_group="broad",
                lifecycle_status="exited",
            ),
        )
        for index in range(5, 7):
            self.portfolios.create_snapshot(
                SnapshotCreateInput(
                    snapshot_date=str(
                        date(2026, 5, 1) + timedelta(days=7 * index)
                    ),
                    total_assets=10000,
                    cash_balance=10000,
                    holdings=[
                        HoldingInput(
                            product_name="现金",
                            account_type="货币/现金账户",
                            amount=10000,
                            allocation_percent=100,
                            category="cash",
                        )
                    ],
                )
            )

        result = PerformanceService(self.database).get_analysis()
        exited = result["exited_products"][0]

        self.assertIsNotNone(exited["returns"][4])
        self.assertEqual(exited["data_status"], "available")
        self.assertEqual(result["active_products"], [])

    def test_ranking_labels_include_account_and_liquidity_is_excluded(self) -> None:
        for index in range(5):
            self.portfolios.create_snapshot(
                SnapshotCreateInput(
                    snapshot_date=str(
                        date(2026, 5, 1) + timedelta(days=7 * index)
                    ),
                    total_assets=160000,
                    cash_balance=10000,
                    weekly_return_amount=2500,
                    external_net_flow_amount=0,
                    external_flow_confirmed=True,
                    holdings=[
                        HoldingInput(
                            product_name="同名产品",
                            account_type="账户甲",
                            amount=100000,
                            allocation_percent=62.5,
                            category="equity",
                            weekly_pnl_amount=2000,
                        ),
                        HoldingInput(
                            product_name="同名产品",
                            account_type="账户乙",
                            amount=50000,
                            allocation_percent=31.25,
                            category="equity",
                            weekly_pnl_amount=500,
                        ),
                        HoldingInput(
                            product_name="现金",
                            account_type="货币/现金账户",
                            amount=10000,
                            allocation_percent=6.25,
                            category="cash",
                        ),
                    ],
                )
            )

        result = PerformanceService(self.database).get_analysis()

        self.assertEqual(len(result["active_products"]), 2)
        self.assertEqual(
            {row[0] for row in result["comparison"][4]},
            {"同名产品 · 账户甲", "同名产品 · 账户乙"},
        )
        all_products = (
            result["active_products"]
            + result["objective_products"]
            + result["exited_products"]
        )
        self.assertNotIn("现金", {item["name"] for item in all_products})


if __name__ == "__main__":
    unittest.main()
