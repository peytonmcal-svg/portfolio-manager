"""Live stock prices and portfolio value calculations."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math

import yfinance

from portfolio_app.db.holdings import Holding


@dataclass(frozen=True)
class PositionValue:
    ticker: str
    shares: float
    buy_price: float
    current_price: float | None
    cost_basis: float
    market_value: float | None
    gain_loss: float | None
    gain_loss_percent: float | None


@dataclass(frozen=True)
class PortfolioValue:
    cost_basis: float
    market_value: float
    gain_loss: float
    gain_loss_percent: float | None
    valued_positions: int


def fetch_current_price(ticker: str) -> float:
    """Fetch the latest available price from Yahoo Finance."""
    raw_price = yfinance.Ticker(ticker).fast_info["last_price"]
    price = float(raw_price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"Yahoo Finance returned an invalid price for {ticker}.")
    return price


def calculate_position_value(
    ticker: str,
    shares: float,
    buy_price: float,
    current_price: float | None,
) -> PositionValue:
    """Calculate market value and unrealized gain/loss for one holding."""
    if not math.isfinite(shares) or shares <= 0:
        raise ValueError("Shares must be greater than zero.")
    if not math.isfinite(buy_price) or buy_price <= 0:
        raise ValueError("Buy price must be greater than zero.")
    cost_basis = shares * buy_price
    if current_price is None:
        return PositionValue(
            ticker=ticker,
            shares=shares,
            buy_price=buy_price,
            current_price=None,
            cost_basis=cost_basis,
            market_value=None,
            gain_loss=None,
            gain_loss_percent=None,
        )
    if not math.isfinite(current_price) or current_price <= 0:
        raise ValueError("Current price must be greater than zero.")

    market_value = shares * current_price
    gain_loss = market_value - cost_basis
    return PositionValue(
        ticker=ticker,
        shares=shares,
        buy_price=buy_price,
        current_price=current_price,
        cost_basis=cost_basis,
        market_value=market_value,
        gain_loss=gain_loss,
        gain_loss_percent=(gain_loss / cost_basis) * 100,
    )


def calculate_portfolio_value(
    positions: Iterable[PositionValue],
) -> PortfolioValue:
    """Total only positions with a price; unpriced positions are excluded."""
    priced_positions = [
        position for position in positions if position.current_price is not None
    ]
    cost_basis = sum(position.cost_basis for position in priced_positions)
    market_value = sum(
        position.market_value
        for position in priced_positions
        if position.market_value is not None
    )
    gain_loss = market_value - cost_basis
    return PortfolioValue(
        cost_basis=cost_basis,
        market_value=market_value,
        gain_loss=gain_loss,
        gain_loss_percent=(gain_loss / cost_basis * 100) if cost_basis else None,
        valued_positions=len(priced_positions),
    )


def calculate_holdings_values(
    holdings: Iterable[Holding],
    prices: Mapping[str, float],
) -> list[PositionValue]:
    """Calculate every holding using its ticker's available cached/live price."""
    return [
        calculate_position_value(
            ticker=holding.ticker,
            shares=holding.shares,
            buy_price=holding.buy_price,
            current_price=prices.get(holding.ticker),
        )
        for holding in holdings
    ]
