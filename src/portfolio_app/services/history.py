"""Daily portfolio value rebuilt from buy dates and historical closing prices."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from portfolio_app.db.holdings import Holding

# ticker -> {"YYYY-MM-DD": value}
DailySeries = Mapping[str, Mapping[str, float]]


@dataclass(frozen=True)
class ValuePoint:
    date: str
    market_value: float
    invested: float


def calculate_value_history(
    holdings: Iterable[Holding],
    price_history: DailySeries,
) -> list[ValuePoint]:
    """Portfolio value and money invested on each trading day.

    Assumes no sales: a holding counts from its buy date onward. A holding
    enters the totals (value and invested) once it has a known price on or
    before that day; a ticker missing a price on one day uses its last close.
    """
    holdings = list(holdings)
    if not holdings:
        return []
    first_buy = min(holding.buy_date for holding in holdings)
    tickers = {holding.ticker for holding in holdings}
    all_dates = sorted(
        {day for ticker in tickers for day in price_history.get(ticker, {})}
    )

    last_close: dict[str, float] = {}
    points: list[ValuePoint] = []
    for day in all_dates:
        for ticker in tickers:
            close = price_history.get(ticker, {}).get(day)
            if close is not None:
                last_close[ticker] = close
        if day < first_buy:
            continue

        market_value = 0.0
        invested = 0.0
        for holding in holdings:
            close = last_close.get(holding.ticker)
            if holding.buy_date <= day and close is not None:
                market_value += holding.shares * close
                invested += holding.shares * holding.buy_price
        if invested > 0:
            points.append(ValuePoint(day, market_value, invested))
    return points


def tickers_without_history(
    holdings: Iterable[Holding], price_history: DailySeries
) -> list[str]:
    """Tickers that have no saved price on or after any of their buy dates."""
    missing: set[str] = set()
    for holding in holdings:
        days = price_history.get(holding.ticker, {})
        if not any(day >= holding.buy_date for day in days):
            missing.add(holding.ticker)
    return sorted(missing)


def tickers_split_after_buy(
    holdings: Iterable[Holding], split_history: DailySeries
) -> list[str]:
    """Tickers that split after a buy date.

    Historical prices are split-adjusted, so shares must be entered as the
    post-split count for past values to be correct.
    """
    return sorted(
        {
            holding.ticker
            for holding in holdings
            if any(
                day > holding.buy_date
                for day in split_history.get(holding.ticker, {})
            )
        }
    )
