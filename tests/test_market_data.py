"""Tests for holding and portfolio value calculations."""
import pytest

from portfolio_app.db.holdings import Holding
from portfolio_app.services.market_data import (
    calculate_holdings_values,
    calculate_portfolio_value,
    calculate_position_value,
    fetch_current_price,
    fetch_price_history,
    fetch_sector,
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


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({"quoteType": "EQUITY", "sector": "Technology"}, "Technology"),
        ({"quoteType": "ETF", "category": "Large Blend"}, "ETF / Fund"),
        ({"quoteType": "MUTUALFUND"}, "ETF / Fund"),
        ({"quoteType": "EQUITY"}, "Unknown"),
    ],
)
def test_fetch_sector_labels_stocks_funds_and_unknowns(monkeypatch, info, expected):
    class FakeTicker:
        pass

    FakeTicker.info = info
    monkeypatch.setattr(
        "portfolio_app.services.market_data.yfinance.Ticker",
        lambda ticker: FakeTicker(),
    )

    assert fetch_sector("SPY") == expected


def test_fetch_price_history_reads_closes_and_splits(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame(
        {"Close": [124.8, 129.0], "Stock Splits": [0.0, 4.0]},
        index=pd.DatetimeIndex(
            ["2020-08-28", "2020-08-31"], tz="America/New_York"
        ),
    )

    class FakeTicker:
        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is False
            return frame

    monkeypatch.setattr(
        "portfolio_app.services.market_data.yfinance.Ticker",
        lambda ticker: FakeTicker(),
    )

    closes, splits = fetch_price_history("AAPL", "2020-08-28")

    assert closes == {"2020-08-28": 124.8, "2020-08-31": 129.0}
    assert splits == {"2020-08-31": 4.0}


def test_fetch_price_history_with_no_data_raises(monkeypatch):
    import pandas as pd

    class FakeTicker:
        def history(self, **kwargs):
            return pd.DataFrame()

    monkeypatch.setattr(
        "portfolio_app.services.market_data.yfinance.Ticker",
        lambda ticker: FakeTicker(),
    )

    with pytest.raises(ValueError):
        fetch_price_history("NOPE", "2020-01-01")
