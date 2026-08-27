import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.product_service import ProductService
from app.schemas import HoldingInput, ProductUpdateInput
from app.schemas import SnapshotCreateInput
from app.service import PortfolioService


class ProductServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "portfolio.db")
        self.database.initialize()
        self.service = ProductService(self.database)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_resolve_reuses_same_name_and_account(self) -> None:
        holding = HoldingInput(
            product_name="新宽基",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
            management_role="active_watch",
            comparison_group="broad",
        )
        first_id = self.service.resolve_product(holding)
        second_id = self.service.resolve_product(holding)
        self.assertEqual(first_id, second_id)
        self.assertEqual(len(self.service.list_products()), 1)

    def test_default_role_uses_account_and_category(self) -> None:
        product_id = self.service.resolve_product(HoldingInput(
            product_name="养老金产品",
            account_type="养老金账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        ))
        product = self.service.get_product(product_id)
        self.assertEqual(product.management_role, "long_term")

    def test_update_changes_metadata_without_changing_identity(self) -> None:
        product_id = self.service.resolve_product(HoldingInput(
            product_name="中证全指组合包",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        ))
        updated = self.service.update_product(product_id, ProductUpdateInput(
            management_role="active_watch",
            comparison_group="broad",
            lifecycle_status="planned_exit",
        ))
        self.assertEqual(updated.id, product_id)
        self.assertEqual(updated.lifecycle_status, "planned_exit")

    def test_new_snapshot_holdings_reuse_a_stable_product_id(self) -> None:
        portfolio_service = PortfolioService(self.database)
        holding = HoldingInput(
            product_name="全市场指数",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        )
        first = portfolio_service.create_snapshot(SnapshotCreateInput(
            snapshot_date="2026-08-20",
            total_assets=10000,
            cash_balance=0,
            holdings=[holding],
        ))
        second = portfolio_service.create_snapshot(SnapshotCreateInput(
            snapshot_date="2026-08-27",
            total_assets=10000,
            cash_balance=0,
            holdings=[holding],
        ))

        self.assertIsNotNone(first.holdings[0].product_id)
        self.assertEqual(first.holdings[0].product_id, second.holdings[0].product_id)
        self.assertEqual(len(self.service.list_products()), 1)

    def test_invalid_product_update_keeps_existing_holdings(self) -> None:
        portfolio_service = PortfolioService(self.database)
        original = portfolio_service.create_snapshot(SnapshotCreateInput(
            snapshot_date="2026-08-20",
            total_assets=10000,
            cash_balance=0,
            holdings=[HoldingInput(
                product_name="原产品",
                account_type="普通账户",
                amount=10000,
                allocation_percent=100,
                category="equity",
            )],
        ))

        with self.assertRaisesRegex(ValueError, "Product 999 not found"):
            portfolio_service.update_snapshot(original.id, SnapshotCreateInput(
                snapshot_date="2026-08-20",
                total_assets=10000,
                cash_balance=0,
                holdings=[HoldingInput(
                    product_id=999,
                    product_name="无效产品",
                    account_type="普通账户",
                    amount=10000,
                    allocation_percent=100,
                    category="equity",
                )],
            ))

        self.assertEqual(
            portfolio_service.get_snapshot(original.id).holdings[0].product_name,
            "原产品",
        )

    def test_bound_product_id_must_match_name_and_account_identity(self) -> None:
        product_id = self.service.resolve_product(HoldingInput(
            product_name="稳定身份产品",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        ))
        portfolio_service = PortfolioService(self.database)

        for product_name, account_type in (
            ("冒名产品", "普通账户"),
            ("稳定身份产品", "养老金账户"),
        ):
            with self.subTest(product_name=product_name, account_type=account_type):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    portfolio_service.create_snapshot(SnapshotCreateInput(
                        snapshot_date=(
                            "2026-09-03"
                            if account_type == "普通账户"
                            else "2026-09-10"
                        ),
                        total_assets=10000,
                        cash_balance=0,
                        holdings=[HoldingInput(
                            product_id=product_id,
                            product_name=product_name,
                            account_type=account_type,
                            amount=10000,
                            allocation_percent=100,
                            category="equity",
                        )],
                    ))

    def test_snapshot_rejects_duplicate_product_id_rows(self) -> None:
        product_id = self.service.resolve_product(HoldingInput(
            product_name="唯一产品",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        ))
        holding = HoldingInput(
            product_id=product_id,
            product_name="唯一产品",
            account_type="普通账户",
            amount=5000,
            allocation_percent=50,
            category="equity",
        )

        with self.assertRaisesRegex(ValueError, "Duplicate product_id"):
            PortfolioService(self.database).create_snapshot(SnapshotCreateInput(
                snapshot_date="2026-09-03",
                total_assets=10000,
                cash_balance=0,
                holdings=[holding, holding],
            ))

    def test_failed_snapshot_write_rolls_back_new_product_profile(self) -> None:
        portfolio_service = PortfolioService(self.database)
        portfolio_service.create_snapshot(SnapshotCreateInput(
            snapshot_date="2026-09-03",
            total_assets=10000,
            cash_balance=0,
            holdings=[],
        ))
        before = len(self.service.list_products())

        with self.assertRaises(sqlite3.IntegrityError):
            portfolio_service.create_snapshot(SnapshotCreateInput(
                snapshot_date="2026-09-03",
                total_assets=10000,
                cash_balance=0,
                holdings=[HoldingInput(
                    product_name="不应残留的产品",
                    account_type="普通账户",
                    amount=10000,
                    allocation_percent=100,
                    category="equity",
                )],
            ))

        self.assertEqual(len(self.service.list_products()), before)
