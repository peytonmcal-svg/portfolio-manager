"""Tests for holding and portfolio value calculations."""
import pytest

from portfolio_app.db.holdings import Holding
from portfolio_app.services.market_data import (
    calculate_holdings_values,
    calculate_portfolio_value,
    calculate_position_value,
    fetch_current_price,
)


@pytest.mark.parametrize(
    ("current_price", "market_value", "gain_loss", "gain_loss_percent"),
    [
        (120, 600, 100, 20),
        (80, 400, -100, -20),
        (100, 500, 0, 0),
    ],
)
def test_calculates_position_market_value_and_return(
    current_price, market_value, gain_loss, gain_loss_percent
):
    result = calculate_position_value("AAPL", 5, 100, current_price)

    assert result.cost_basis == 500
    assert result.market_value == market_value
    assert result.gain_loss == gain_loss
    assert result.gain_loss_percent == gain_loss_percent


def test_missing_price_does_not_create_false_gain_or_market_value():
    result = calculate_position_value("AAPL", 5, 100, None)

    assert result.cost_basis == 500
    assert result.market_value is None
    assert result.gain_loss is None
    assert result.gain_loss_percent is None


def test_portfolio_totals_include_only_positions_with_prices():
    holdings = [
        Holding(1, 1, "AAPL", 5, 100, "2025-01-01"),
        Holding(2, 1, "MSFT", 2, 200, "2025-01-01"),
    ]

    positions = calculate_holdings_values(holdings, {"AAPL": 120})
    total = calculate_portfolio_value(positions)

    assert total.cost_basis == 500
    assert total.market_value == 600
    assert total.gain_loss == 100
    assert total.gain_loss_percent == 20
    assert total.valued_positions == 1
    assert positions[1].market_value is None


def test_portfolio_with_no_prices_has_no_percentage_return():
    holding = Holding(1, 1, "AAPL", 5, 100, "2025-01-01")

    total = calculate_portfolio_value(calculate_holdings_values([holding], {}))

    assert total.cost_basis == 0
    assert total.market_value == 0
    assert total.gain_loss == 0
    assert total.gain_loss_percent is None
    assert total.valued_positions == 0


def test_fetch_current_price_uses_yahoo_fast_info(monkeypatch):
    class FakeTicker:
        fast_info = {"last_price": 123.45}

    monkeypatch.setattr(
        "portfolio_app.services.market_data.yfinance.Ticker",
        lambda ticker: FakeTicker(),
    )

    assert fetch_current_price("AAPL") == 123.45


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_fetch_current_price_rejects_invalid_quotes(monkeypatch, price):
    class FakeTicker:
        fast_info = {"last_price": price}

    monkeypatch.setattr(
        "portfolio_app.services.market_data.yfinance.Ticker",
        lambda ticker: FakeTicker(),
    )

    with pytest.raises(ValueError):
        fetch_current_price("AAPL")
