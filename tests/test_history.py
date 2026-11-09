"""Tests for rebuilding daily portfolio value from historical prices."""
import pytest

from portfolio_app.db.holdings import Holding
from portfolio_app.services.history import (
    BenchmarkPoint,
    Comparison,
    ValuePoint,
    calculate_benchmark_history,
    calculate_value_history,
    compare_to_benchmark,
    simple_return_percent,
    tickers_split_after_buy,
    tickers_without_history,
)


def holding(ticker, shares, buy_price, buy_date, holding_id=1):
    return Holding(holding_id, 1, ticker, shares, buy_price, buy_date)


def test_value_on_each_day_is_shares_times_close():
    history = {"AAPL": {"2025-01-02": 100, "2025-01-03": 110}}

    result = calculate_value_history([holding("AAPL", 10, 95, "2025-01-02")], history)

    assert result == [
        ValuePoint("2025-01-02", 1000, 950),
        ValuePoint("2025-01-03", 1100, 950),
    ]


def test_holding_is_not_counted_before_its_buy_date():
    history = {
        "AAPL": {"2025-01-02": 100, "2025-01-03": 100, "2025-01-06": 100},
        "KO": {"2025-01-02": 50, "2025-01-03": 50, "2025-01-06": 60},
    }
    holdings = [
        holding("AAPL", 1, 100, "2025-01-02", 1),
        holding("KO", 10, 50, "2025-01-06", 2),
    ]

    result = calculate_value_history(holdings, history)

    assert [(p.date, p.market_value, p.invested) for p in result] == [
        ("2025-01-02", 100, 100),
        ("2025-01-03", 100, 100),
        ("2025-01-06", 700, 600),
    ]


def test_chart_starts_at_first_buy_date():
    history = {"AAPL": {"2024-12-31": 90, "2025-01-02": 100}}

    result = calculate_value_history([holding("AAPL", 1, 100, "2025-01-02")], history)

    assert [point.date for point in result] == ["2025-01-02"]


def test_weekend_buy_starts_on_next_trading_day():
    history = {"AAPL": {"2025-01-03": 100, "2025-01-06": 105}}  # Fri, Mon

    result = calculate_value_history(
        [holding("AAPL", 2, 100, "2025-01-04")], history  # Saturday
    )

    assert result == [ValuePoint("2025-01-06", 210, 200)]


def test_missing_close_uses_last_known_price():
    history = {
        "AAPL": {"2025-01-02": 100, "2025-01-03": 120},
        "VOD": {"2025-01-02": 10},  # no price on 01-03
    }
    holdings = [
        holding("AAPL", 1, 100, "2025-01-02", 1),
        holding("VOD", 5, 10, "2025-01-02", 2),
    ]

    result = calculate_value_history(holdings, history)

    assert result[-1] == ValuePoint("2025-01-03", 170, 150)


def test_two_buys_of_the_same_ticker_add_up():
    history = {"AAPL": {"2025-01-02": 100, "2025-01-03": 100, "2025-01-06": 120}}
    holdings = [
        holding("AAPL", 1, 90, "2025-01-02", 1),
        holding("AAPL", 2, 100, "2025-01-06", 2),
    ]

    result = calculate_value_history(holdings, history)

    assert result[0] == ValuePoint("2025-01-02", 100, 90)
    assert result[-1] == ValuePoint("2025-01-06", 360, 290)


def test_holding_without_history_is_left_out_of_value_and_invested():
    history = {"AAPL": {"2025-01-02": 100}}
    holdings = [
        holding("AAPL", 1, 100, "2025-01-02", 1),
        holding("XYZ", 10, 10, "2025-01-02", 2),
    ]

    result = calculate_value_history(holdings, history)

    assert result == [ValuePoint("2025-01-02", 100, 100)]
    assert tickers_without_history(holdings, history) == ["XYZ"]


def test_no_holdings_or_no_history_gives_empty_chart():
    assert calculate_value_history([], {"AAPL": {"2025-01-02": 1}}) == []
    assert calculate_value_history([holding("AAPL", 1, 1, "2025-01-02")], {}) == []


def test_split_after_buy_date_is_flagged():
    splits = {"AAPL": {"2020-08-31": 4.0}, "TSLA": {"2020-08-31": 5.0}}
    holdings = [
        holding("AAPL", 1, 100, "2020-01-02", 1),  # bought before split
        holding("TSLA", 1, 100, "2021-01-04", 2),  # bought after split
    ]

    assert tickers_split_after_buy(holdings, splits) == ["AAPL"]


# --- S&P 500 (SPY) comparison ---------------------------------------------

def test_single_buy_puts_same_dollars_into_spy():
    spy = {"2025-01-02": 500, "2025-01-03": 550}

    result = calculate_benchmark_history(
        [holding("AAPL", 10, 100, "2025-01-02")], spy  # $1,000 -> 2 SPY shares
    )

    assert result == [
        BenchmarkPoint("2025-01-02", 1000, 1000),
        BenchmarkPoint("2025-01-03", 1100, 1000),
    ]


def test_two_buys_on_different_dates_each_buy_spy_at_that_days_close():
    spy = {"2025-01-02": 500, "2025-01-03": 400, "2025-01-06": 800}
    holdings = [
        holding("AAPL", 5, 100, "2025-01-02", 1),  # $500 -> 1 share at 500
        holding("KO", 20, 40, "2025-01-03", 2),  # $800 -> 2 shares at 400
    ]

    result = calculate_benchmark_history(holdings, spy)

    assert result == [
        BenchmarkPoint("2025-01-02", 500, 500),
        BenchmarkPoint("2025-01-03", 1200, 1300),  # 3 shares x 400
        BenchmarkPoint("2025-01-06", 2400, 1300),  # 3 shares x 800
    ]


def test_weekend_buy_uses_next_trading_days_spy_close():
    spy = {"2025-01-03": 500, "2025-01-06": 400, "2025-01-07": 440}  # Fri, Mon, Tue

    result = calculate_benchmark_history(
        [holding("AAPL", 4, 100, "2025-01-04")], spy  # Saturday, $400
    )

    assert result == [
        BenchmarkPoint("2025-01-06", 400, 400),  # 1 share bought Monday
        BenchmarkPoint("2025-01-07", 440, 400),
    ]


def test_buy_after_last_spy_close_is_left_out():
    spy = {"2025-01-02": 500}

    result = calculate_benchmark_history(
        [
            holding("AAPL", 5, 100, "2025-01-02", 1),
            holding("KO", 1, 50, "2025-01-10", 2),
        ],
        spy,
    )

    assert result == [BenchmarkPoint("2025-01-02", 500, 500)]


def test_no_holdings_or_no_spy_history_gives_no_comparison():
    assert calculate_benchmark_history([], {"2025-01-02": 500}) == []
    assert calculate_benchmark_history([holding("A", 1, 1, "2025-01-02")], {}) == []


def test_simple_return_percent_matches_hand_calculation():
    assert simple_return_percent(1184, 1000) == pytest.approx(18.4)
    assert simple_return_percent(900, 1000) == pytest.approx(-10)
    assert simple_return_percent(100, 0) is None


def test_comparison_uses_same_dollars_and_latest_shared_date():
    prices = {
        "AAPL": {"2025-01-02": 100, "2025-01-03": 120, "2025-01-06": 130},
        "SPY": {"2025-01-02": 500, "2025-01-03": 525},  # no 01-06 yet
    }
    holdings = [holding("AAPL", 10, 100, "2025-01-02")]

    points = calculate_value_history(holdings, prices)
    benchmark = calculate_benchmark_history(holdings, prices["SPY"])
    comparison = compare_to_benchmark(points, benchmark)

    assert comparison == Comparison(
        date="2025-01-03",
        portfolio_value=1200,
        portfolio_return_percent=pytest.approx(20),
        benchmark_value=1050,
        benchmark_return_percent=pytest.approx(5),
        invested=1000,
    )
    # Both sides put the same dollars to work on the comparison date.
    assert benchmark[-1].invested == points[1].invested


def test_comparison_is_none_without_overlapping_dates():
    assert compare_to_benchmark([], []) is None
    assert (
        compare_to_benchmark(
            [ValuePoint("2025-01-02", 1, 1)], [BenchmarkPoint("2025-01-03", 1, 1)]
        )
        is None
    )
