from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS weekly_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL UNIQUE,
                    total_assets REAL NOT NULL,
                    cash_balance REAL NOT NULL,
                    weekly_return_amount REAL NOT NULL DEFAULT 0,
                    ytd_return_amount REAL NOT NULL DEFAULT 0,
                    data_cutoff_notes TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    allocation_percent REAL NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'hold',
                    weekly_pnl_amount REAL NOT NULL DEFAULT 0,
                    valuation_cutoff_date TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(snapshot_id) REFERENCES weekly_snapshots(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS target_allocation_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    equity_min REAL NOT NULL,
                    equity_max REAL NOT NULL,
                    fixed_income_min REAL NOT NULL,
                    fixed_income_max REAL NOT NULL,
                    cash_min REAL NOT NULL,
                    cash_max REAL NOT NULL,
                    gold_min REAL NOT NULL,
                    gold_max REAL NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(weekly_snapshots)").fetchall()
            }
            if "data_cutoff_notes" not in columns:
                connection.execute(
                    "ALTER TABLE weekly_snapshots ADD COLUMN data_cutoff_notes TEXT NOT NULL DEFAULT ''"
                )

            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(holdings)").fetchall()
            }
            if "weekly_pnl_amount" not in columns:
                connection.execute(
                    "ALTER TABLE holdings ADD COLUMN weekly_pnl_amount REAL NOT NULL DEFAULT 0"
                )
            if "valuation_cutoff_date" not in columns:
                connection.execute(
                    "ALTER TABLE holdings ADD COLUMN valuation_cutoff_date TEXT NOT NULL DEFAULT ''"
                )

            connection.execute(
                """
                INSERT OR IGNORE INTO target_allocation_settings (
                    id,
                    equity_min,
                    equity_max,
                    fixed_income_min,
                    fixed_income_max,
                    cash_min,
                    cash_max,
                    gold_min,
                    gold_max
                ) VALUES (1, 48, 55, 35, 42, 5, 10, 0, 5)
                """
            )
