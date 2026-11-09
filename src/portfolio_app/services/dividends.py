"""Dividend income: estimates from dividend history plus manual entries."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from portfolio_app.db.holdings import Holding, ManualDividend

ESTIMATED = "Estimated"
MANUAL = "Manual"


@dataclass(frozen=True)
class DividendEntry:
    ticker: str
    date: str  # ex-dividend date for estimates; the user's date for manual ones
    shares: float | None
    per_share: float | None
    amount: float
    source: str  # ESTIMATED or MANUAL
    manual_id: int | None = None


def estimate_dividends(
    holdings: Iterable[Holding],
    dividend_history: Mapping[str, Mapping[str, float]],
) -> list[DividendEntry]:
    """Shares held x dividend per share, for each dividend after a buy.

    A holding earns a dividend only if it was bought before the
    ex-dividend date (buying on or after that date doesn't qualify).
    Holdings without a buy date are skipped. Assumes no shares were sold.
    """
    lots_by_ticker: dict[str, list[Holding]] = {}
    for holding in holdings:
        if holding.buy_date is not None:
            lots_by_ticker.setdefault(holding.ticker, []).append(holding)

    entries: list[DividendEntry] = []
    for ticker, lots in lots_by_ticker.items():
        for ex_date, per_share in dividend_history.get(ticker, {}).items():
            shares = sum(lot.shares for lot in lots if lot.buy_date < ex_date)
            if shares > 0:
                entries.append(
                    DividendEntry(
                        ticker=ticker,
                        date=ex_date,
                        shares=shares,
                        per_share=per_share,
                        amount=shares * per_share,
                        source=ESTIMATED,
                    )
                )
    return entries


def combine_dividends(
    estimated: Iterable[DividendEntry],
    manual: Iterable[ManualDividend],
) -> list[DividendEntry]:
    """One log, newest first; a manual entry replaces the estimate for the
    same ticker and date (a $0 manual entry means "not received").
    """
    log: dict[tuple[str, str], DividendEntry] = {
        (entry.ticker, entry.date): entry for entry in estimated
    }
    for dividend in manual:
        estimate = log.get((dividend.ticker, dividend.date))
        shares = estimate.shares if estimate else None
        log[(dividend.ticker, dividend.date)] = DividendEntry(
            ticker=dividend.ticker,
            date=dividend.date,
            shares=shares,
            per_share=dividend.amount / shares if shares else None,
            amount=dividend.amount,
            source=MANUAL,
            manual_id=dividend.id,
        )
    return sorted(log.values(), key=lambda entry: (entry.date, entry.ticker), reverse=True)


def totals_by_year(entries: Iterable[DividendEntry]) -> dict[str, float]:
    """Total dividends per calendar year, newest year first."""
    totals: dict[str, float] = {}
    for entry in entries:
        year = entry.date[:4]
        totals[year] = totals.get(year, 0.0) + entry.amount
    return dict(sorted(totals.items(), reverse=True))
