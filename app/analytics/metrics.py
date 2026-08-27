from __future__ import annotations

from app.analytics.returns import compound_return


def drawdown_stats(nav_values: list[float], dates: list[str]) -> dict[str, float | str]:
    peak = nav_values[0]
    peak_date = dates[0]
    max_drawdown = 0.0
    for nav, date in zip(nav_values, dates, strict=True):
        if nav > peak:
            peak, peak_date = nav, date
        max_drawdown = min(max_drawdown, nav / peak - 1)
    return {
        "high_nav": peak,
        "high_date": peak_date,
        "current_drawdown": nav_values[-1] / peak - 1,
        "max_drawdown": max_drawdown,
    }


def momentum_delta(values: list[float | None]) -> dict[str, float | str] | None:
    if len(values) < 8:
        return None
    previous = compound_return(values[-8:-4], 4)
    recent = compound_return(values[-4:], 4)
    if previous is None or recent is None:
        return None
    delta = recent - previous
    return {
        "previous_4": previous,
        "recent_4": recent,
        "delta": delta,
        "direction": "strengthening" if delta > 0 else "weakening" if delta < 0 else "flat",
    }


def streak(values: list[float | None], threshold: float = 0.0005) -> tuple[str, int]:
    count = 0
    direction = "flat"
    for value in reversed(values):
        current = "up" if value is not None and value > threshold else (
            "down" if value is not None and value < -threshold else "flat"
        )
        if current == "flat" or (direction != "flat" and current != direction):
            break
        direction = current
        count += 1
    return direction, count


def rank_horizon(
    values: list[tuple[str, float | None]],
) -> list[tuple[str, float, int]]:
    available = [(name, value) for name, value in values if value is not None]
    if len(available) < 2:
        return []
    ordered = sorted(available, key=lambda item: float(item[1]), reverse=True)
    return [(name, float(value), index + 1) for index, (name, value) in enumerate(ordered)]
