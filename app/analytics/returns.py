from __future__ import annotations

from math import prod


def infer_external_flow(current_assets: float, prior_assets: float, pnl: float) -> float:
    return current_assets - prior_assets - pnl


def modified_dietz_return(
    pnl: float, prior_assets: float, external_net_flow: float
) -> float | None:
    denominator = prior_assets + 0.5 * external_net_flow
    return pnl / denominator if denominator > 0 else None


def product_period_return(
    pnl: float,
    prior_amount: float,
    transaction_amount: float,
    contiguous: bool,
) -> float | None:
    if not contiguous or prior_amount <= 0:
        return None
    denominator = prior_amount + 0.5 * transaction_amount
    return pnl / denominator if denominator > 0 else None


def compound_return(values: list[float | None], periods: int) -> float | None:
    window = values[-periods:]
    if len(window) != periods or any(value is None for value in window):
        return None
    return prod(1 + float(value) for value in window) - 1


def chain_nav(values: list[float | None], base: float = 1000) -> list[float | None]:
    result: list[float | None] = [base]
    current: float | None = base
    for value in values:
        current = None if current is None or value is None else current * (1 + value)
        result.append(current)
    return result
