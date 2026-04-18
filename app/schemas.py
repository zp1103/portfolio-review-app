from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field


Category = Literal["equity", "fixed_income", "cash", "gold", "other"]
Action = Literal["buy", "sell", "hold", "rebalance"]


class HoldingInput(BaseModel):
    product_name: str = Field(min_length=1, max_length=100)
    account_type: str = Field(min_length=1, max_length=50)
    amount: float = Field(ge=0)
    allocation_percent: float = Field(ge=0, le=100)
    category: Category
    action: Action = "hold"
    weekly_pnl_amount: float = 0
    valuation_cutoff_date: str = ""
    notes: str = ""


class SnapshotCreateInput(BaseModel):
    snapshot_date: str
    total_assets: float = Field(gt=0)
    cash_balance: float = Field(ge=0)
    weekly_return_amount: float = 0
    ytd_return_amount: float = 0
    data_cutoff_notes: str = ""
    notes: str = ""
    holdings: list[HoldingInput] = Field(default_factory=list)


class HoldingRecord(HoldingInput):
    id: int
    snapshot_id: int


class SnapshotRecord(BaseModel):
    id: int
    snapshot_date: str
    total_assets: float
    cash_balance: float
    weekly_return_amount: float
    ytd_return_amount: float
    data_cutoff_notes: str
    notes: str
    holdings: list[HoldingRecord] = Field(default_factory=list)


class CategorySummary(BaseModel):
    amount: float
    percent: float


class AllocationSummary(BaseModel):
    total_assets: float
    categories: dict[str, CategorySummary]


class TargetRange(BaseModel):
    min: float
    max: float


def snapshot_from_row(row: Mapping[str, object], holdings: list[HoldingRecord]) -> SnapshotRecord:
    return SnapshotRecord(
        id=int(row["id"]),
        snapshot_date=str(row["snapshot_date"]),
        total_assets=float(row["total_assets"]),
        cash_balance=float(row["cash_balance"]),
        weekly_return_amount=float(row["weekly_return_amount"]),
        ytd_return_amount=float(row["ytd_return_amount"]),
        data_cutoff_notes=str(row["data_cutoff_notes"] or ""),
        notes=str(row["notes"] or ""),
        holdings=holdings,
    )


def holding_from_row(row: Mapping[str, object]) -> HoldingRecord:
    return HoldingRecord(
        id=int(row["id"]),
        snapshot_id=int(row["snapshot_id"]),
        product_name=str(row["product_name"]),
        account_type=str(row["account_type"]),
        amount=float(row["amount"]),
        allocation_percent=float(row["allocation_percent"]),
        category=str(row["category"]),
        action=str(row["action"]),
        weekly_pnl_amount=float(row["weekly_pnl_amount"] or 0),
        valuation_cutoff_date=str(row["valuation_cutoff_date"] or ""),
        notes=str(row["notes"] or ""),
    )
