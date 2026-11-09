"""Tests for allocation by holding and by sector."""
import pytest

from portfolio_app.services.allocation import (
    allocation_by_holding,
    allocation_by_sector,
    calculate_allocation,
)
from portfolio_app.services.market_data import calculate_position_value


def position(ticker, shares, price):
    return calculate_position_value(ticker, shares, 10, price)


def test_holding_allocation_is_share_of_total_market_value_largest_first():
    positions = [position("KO", 10, 10), position("AAPL", 30, 10)]

    result = allocation_by_holding(positions)

    assert [item.label for item in result] == ["AAPL", "KO"]
    assert [item.market_value for item in result] == [300, 100]
    assert [item.percent for item in result] == [75, 25]


def test_lots_of_the_same_ticker_are_combined():
    positions = [position("AAPL", 1, 100), position("AAPL", 1, 100)]

    result = allocation_by_holding(positions)

    assert len(result) == 1
    assert result[0].market_value == 200
    assert result[0].percent == 100


def test_unpriced_positions_are_excluded():
    positions = [position("AAPL", 1, 100), position("MSFT", 1, None)]

    result = allocation_by_holding(positions)

    assert [item.label for item in result] == ["AAPL"]
    assert result[0].percent == 100


def test_no_priced_positions_gives_empty_allocation():
    assert allocation_by_holding([position("AAPL", 1, None)]) == []
    assert allocation_by_holding([]) == []


def test_sector_allocation_groups_tickers_and_labels_missing_as_unknown():
    positions = [
        position("AAPL", 1, 100),
        position("MSFT", 1, 100),
        position("KO", 1, 100),
        position("XYZ", 1, 100),
    ]
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "KO": "Consumer Defensive"}

    result = allocation_by_sector(positions, sectors)

    assert [(item.label, item.percent) for item in result] == [
        ("Technology", 50),
        ("Consumer Defensive", 25),
        ("Unknown", 25),
    ]


def test_groups_beyond_the_limit_fold_into_other():
    positions = [position(f"T{n}", n, 10) for n in range(1, 6)]  # values 10..50

    result = allocation_by_holding(positions, max_slices=3)

    assert [item.label for item in result] == ["T5", "T4", "Other"]
    assert [item.market_value for item in result] == [50, 40, 60]
    assert sum(item.percent for item in result) == pytest.approx(100)


def test_max_slices_must_be_positive():
    with pytest.raises(ValueError):
        calculate_allocation([], lambda p: p.ticker, max_slices=0)
