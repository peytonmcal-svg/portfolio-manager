"""Portfolio allocation (share of total market value) by holding or sector."""
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from portfolio_app.services.market_data import UNKNOWN_SECTOR, PositionValue

OTHER_LABEL = "Other"


@dataclass(frozen=True)
class AllocationSlice:
    label: str
    market_value: float
    percent: float


def calculate_allocation(
    positions: Iterable[PositionValue],
    label_for: Callable[[PositionValue], str],
    max_slices: int = 10,
) -> list[AllocationSlice]:
    """Group priced positions by label, largest first.

    Positions without a price are excluded, matching the portfolio totals.
    Groups beyond ``max_slices`` are combined into a final "Other" slice.
    """
    if max_slices < 1:
        raise ValueError("max_slices must be at least 1.")
    totals: dict[str, float] = {}
    for position in positions:
        if position.market_value is None:
            continue
        label = label_for(position)
        totals[label] = totals.get(label, 0.0) + position.market_value

    grand_total = sum(totals.values())
    if grand_total <= 0:
        return []

    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > max_slices:
        kept = ranked[: max_slices - 1]
        other_value = sum(value for _, value in ranked[max_slices - 1 :])
        ranked = [*kept, (OTHER_LABEL, other_value)]

    return [
        AllocationSlice(
            label=label,
            market_value=value,
            percent=value / grand_total * 100,
        )
        for label, value in ranked
    ]


def allocation_by_holding(
    positions: Iterable[PositionValue], max_slices: int = 10
) -> list[AllocationSlice]:
    """Several buy lots of the same ticker count as one holding."""
    return calculate_allocation(
        positions, lambda position: position.ticker, max_slices
    )


def allocation_by_sector(
    positions: Iterable[PositionValue],
    sectors: dict[str, str],
    max_slices: int = 10,
) -> list[AllocationSlice]:
    """Tickers with no saved sector are grouped as "Unknown"."""
    return calculate_allocation(
        positions,
        lambda position: sectors.get(position.ticker, UNKNOWN_SECTOR),
        max_slices,
    )
