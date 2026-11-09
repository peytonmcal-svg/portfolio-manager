"""Tests for rebuilding daily portfolio value from historical prices."""
from portfolio_app.db.holdings import Holding
from portfolio_app.services.history import (
    ValuePoint,
    calculate_value_history,
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
