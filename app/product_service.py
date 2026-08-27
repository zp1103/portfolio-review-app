from app.db import Database
from app.schemas import HoldingInput, ProductRecord, ProductUpdateInput


class ProductService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_products(self) -> list[ProductRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM portfolio_products ORDER BY account_type, canonical_name"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_product(self, product_id: int) -> ProductRecord:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_products WHERE id = ?", (product_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Product {product_id} not found")
        return self._from_row(row)

    def resolve_product(self, holding: HoldingInput) -> int:
        if holding.product_id is not None:
            self.get_product(holding.product_id)
            return holding.product_id
        default_role = (
            "long_term" if holding.account_type == "养老金账户"
            else "liquidity" if holding.category == "cash"
            else "stable" if holding.category == "fixed_income"
            else "active_watch"
        )
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO portfolio_products (
                    canonical_name, account_type, management_role,
                    comparison_group, lifecycle_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    holding.product_name,
                    holding.account_type,
                    holding.management_role or default_role,
                    holding.comparison_group or "other",
                    holding.lifecycle_status or "active",
                ),
            )
            row = connection.execute(
                """
                SELECT id FROM portfolio_products
                WHERE canonical_name = ? AND account_type = ?
                """,
                (holding.product_name, holding.account_type),
            ).fetchone()
        return int(row["id"])

    def update_product(
        self, product_id: int, payload: ProductUpdateInput
    ) -> ProductRecord:
        with self.database.session() as connection:
            cursor = connection.execute(
                """
                UPDATE portfolio_products
                SET management_role = ?, comparison_group = ?,
                    lifecycle_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    payload.management_role,
                    payload.comparison_group,
                    payload.lifecycle_status,
                    product_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Product {product_id} not found")
        return self.get_product(product_id)

    @staticmethod
    def _from_row(row) -> ProductRecord:
        return ProductRecord(
            id=int(row["id"]),
            canonical_name=str(row["canonical_name"]),
            account_type=str(row["account_type"]),
            management_role=str(row["management_role"]),
            comparison_group=str(row["comparison_group"]),
            lifecycle_status=str(row["lifecycle_status"]),
        )
