"""Daily portfolio value rebuilt from buy dates and historical closing prices."""
from bisect import bisect_left
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from portfolio_app.db.holdings import Holding

BENCHMARK_TICKER = "SPY"

# ticker -> {"YYYY-MM-DD": value}
DailySeries = Mapping[str, Mapping[str, float]]


@dataclass(frozen=True)
class ValuePoint:
    date: str
    market_value: float
    invested: float


@dataclass(frozen=True)
class BenchmarkPoint:
    date: str
    value: float
    invested: float


@dataclass(frozen=True)
class Comparison:
    date: str
    portfolio_value: float
    portfolio_return_percent: float | None
    benchmark_value: float
    benchmark_return_percent: float | None
    invested: float


def split_by_buy_date(
    holdings: Iterable[Holding],
) -> tuple[list[Holding], list[Holding]]:
    """(holdings with a buy date, holdings marked "date missing").

    History and the SPY comparison need a buy date, so they use only the
    first list.
    """
    holdings = list(holdings)
    return (
        [holding for holding in holdings if holding.buy_date is not None],
        [holding for holding in holdings if holding.buy_date is None],
    )


def missing_date_note(undated: Iterable[Holding]) -> str:
    """e.g. "6 holdings left out: buy date missing (AAPL, KO, …)." """
    undated = list(undated)
    tickers = ", ".join(sorted({holding.ticker for holding in undated}))
    noun = "holding" if len(undated) == 1 else "holdings"
    return f"{len(undated)} {noun} left out: buy date missing ({tickers})."


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


def calculate_benchmark_history(
    holdings: Iterable[Holding],
    benchmark_closes: Mapping[str, float],
) -> list[BenchmarkPoint]:
    """Value of buying the benchmark with the same dollars on the same dates.

    Each buy's cost (shares x buy price) buys benchmark shares at the
    benchmark's close on the buy date, or the next trading day if markets
    were closed. Buys after the last saved benchmark close are left out.
    """
    dates = sorted(benchmark_closes)
    lots: list[tuple[str, float, float]] = []  # entry date, shares, dollars
    for holding in holdings:
        index = bisect_left(dates, holding.buy_date)
        if index == len(dates):
            continue
        entry_date = dates[index]
        dollars = holding.shares * holding.buy_price
        lots.append((entry_date, dollars / benchmark_closes[entry_date], dollars))
    if not lots:
        return []

    first_entry = min(entry_date for entry_date, _, _ in lots)
    points: list[BenchmarkPoint] = []
    for day in dates:
        if day < first_entry:
            continue
        shares = sum(lot_shares for entry, lot_shares, _ in lots if entry <= day)
        invested = sum(dollars for entry, _, dollars in lots if entry <= day)
        points.append(BenchmarkPoint(day, shares * benchmark_closes[day], invested))
    return points


def simple_return_percent(value: float, invested: float) -> float | None:
    """(value - money invested) / money invested, as a percent."""
    if invested <= 0:
        return None
    return (value - invested) / invested * 100


def compare_to_benchmark(
    points: Iterable[ValuePoint],
    benchmark_points: Iterable[BenchmarkPoint],
) -> Comparison | None:
    """Compare both on the latest date that each has a value for."""
    benchmark_by_date = {point.date: point for point in benchmark_points}
    for point in reversed(list(points)):
        benchmark = benchmark_by_date.get(point.date)
        if benchmark is None:
            continue
        return Comparison(
            date=point.date,
            portfolio_value=point.market_value,
            portfolio_return_percent=simple_return_percent(
                point.market_value, point.invested
            ),
            benchmark_value=benchmark.value,
            benchmark_return_percent=simple_return_percent(
                benchmark.value, benchmark.invested
            ),
            invested=point.invested,
        )
    return None


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
