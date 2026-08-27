import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import Database


class ProductMigrationTests(unittest.TestCase):
    def test_initialize_backfills_products_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE weekly_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL UNIQUE,
                    total_assets REAL NOT NULL,
                    cash_balance REAL NOT NULL,
                    weekly_return_amount REAL NOT NULL DEFAULT 0,
                    ytd_return_amount REAL NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    allocation_percent REAL NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'hold',
                    notes TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO weekly_snapshots
                    (snapshot_date, total_assets, cash_balance)
                VALUES ('2026-08-21', 120000, 20000);
                INSERT INTO holdings
                    (snapshot_id, product_name, account_type, amount, allocation_percent, category)
                VALUES
                    (1, '养老金中证500增强', '养老金账户', 100000, 83.33, 'equity'),
                    (1, '现金', '货币/现金账户', 20000, 16.67, 'cash');
                """
            )
            connection.commit()
            connection.close()

            database = Database(path)
            database.initialize()
            database.initialize()

            with database.session() as migrated:
                products = migrated.execute(
                    "SELECT canonical_name, management_role FROM portfolio_products ORDER BY id"
                ).fetchall()
                missing = migrated.execute(
                    "SELECT COUNT(*) AS count FROM holdings WHERE product_id IS NULL"
                ).fetchone()["count"]
                snapshot_columns = {
                    row["name"]
                    for row in migrated.execute(
                        "PRAGMA table_info(weekly_snapshots)"
                    ).fetchall()
                }

            self.assertEqual(len(products), 2)
            self.assertEqual(products[0]["management_role"], "long_term")
            self.assertEqual(products[1]["management_role"], "liquidity")
            self.assertEqual(missing, 0)
            self.assertIn("external_net_flow_amount", snapshot_columns)
            self.assertIn("external_flow_confirmed", snapshot_columns)
