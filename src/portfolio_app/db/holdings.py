"""SQLite storage for portfolios and their holdings."""
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import sqlite3

from portfolio_app.config import DB_PATH


@dataclass(frozen=True)
class Holding:
    id: int
    portfolio_id: int
    ticker: str
    shares: float
    buy_price: float
    buy_date: str | None  # None when the buy date is unknown ("date missing")


@dataclass(frozen=True)
class NewHolding:
    """A holding that hasn't been saved yet (e.g. a row from a CSV file)."""

    ticker: str
    shares: float
    buy_price: float
    buy_date: str | None


HOLDINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id)
        ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    shares REAL NOT NULL CHECK (shares > 0),
    buy_price REAL NOT NULL CHECK (buy_price > 0),
    buy_date TEXT
);
"""


def validate_holding(
    ticker: str,
    shares: float,
    buy_price: float,
    buy_date: str | None,
) -> tuple[str, float, float, str | None]:
    """Clean up and check one holding's values; a blank date becomes None."""
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("Enter a ticker symbol.")
    if not math.isfinite(shares) or shares <= 0:
        raise ValueError("Shares must be greater than zero.")
    if not math.isfinite(buy_price) or buy_price <= 0:
        raise ValueError("Buy price must be greater than zero.")
    if buy_date is None or not buy_date.strip():
        return normalized_ticker, shares, buy_price, None
    try:
        parsed_date = date.fromisoformat(buy_date.strip())
    except ValueError as error:
        raise ValueError("Enter a valid buy date.") from error
    return normalized_ticker, shares, buy_price, parsed_date.isoformat()


@dataclass(frozen=True)
class ManualDividend:
    """A dividend the user entered by hand (total dollars received)."""

    id: int
    portfolio_id: int
    ticker: str
    date: str
    amount: float


@dataclass(frozen=True)
class CachedPrice:
    ticker: str
    price: float
    fetched_at: str


@dataclass(frozen=True)
class CachedSector:
    ticker: str
    sector: str
    fetched_at: str


class HoldingRepository:
    """Read and change holdings in a local SQLite database."""

    def __init__(self, database_path: Path = DB_PATH) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            had_dividend_history = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'dividend_history'"
            ).fetchone()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolios (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );
                """
                + HOLDINGS_TABLE_SQL.format(name="holdings")
                + """

                CREATE TABLE IF NOT EXISTS price_cache (
                    ticker TEXT PRIMARY KEY,
                    price REAL NOT NULL CHECK (price > 0),
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sector_cache (
                    ticker TEXT PRIMARY KEY,
                    sector TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    close REAL NOT NULL CHECK (close > 0),
                    PRIMARY KEY (ticker, date)
                );

                CREATE TABLE IF NOT EXISTS split_history (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    ratio REAL NOT NULL CHECK (ratio > 0),
                    PRIMARY KEY (ticker, date)
                );

                CREATE TABLE IF NOT EXISTS history_fetches (
                    ticker TEXT PRIMARY KEY,
                    start_date TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dividend_history (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    per_share REAL NOT NULL CHECK (per_share > 0),
                    PRIMARY KEY (ticker, date)
                );

                CREATE TABLE IF NOT EXISTS dividends (
                    id INTEGER PRIMARY KEY,
                    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id)
                        ON DELETE CASCADE,
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL CHECK (amount >= 0),
                    UNIQUE (portfolio_id, ticker, date)
                );
                """
            )
            if not had_dividend_history:
                # History saved before dividends were tracked has none, so
                # download it again on the next refresh.
                connection.execute("DELETE FROM history_fetches")
            self._allow_blank_buy_dates(connection)
            connection.execute(
                "INSERT OR IGNORE INTO portfolios (name) VALUES (?)",
                ("My Portfolio",),
            )

    @staticmethod
    def _allow_blank_buy_dates(connection: sqlite3.Connection) -> None:
        """Upgrade databases made before buy dates were optional.

        SQLite can't relax a NOT NULL rule in place, so the table is copied.
        """
        columns = connection.execute("PRAGMA table_info(holdings)").fetchall()
        if not any(
            column["name"] == "buy_date" and column["notnull"] for column in columns
        ):
            return
        connection.executescript(
            "BEGIN;"
            + HOLDINGS_TABLE_SQL.format(name="holdings_upgraded")
            + """
            INSERT INTO holdings_upgraded
                (id, portfolio_id, ticker, shares, buy_price, buy_date)
            SELECT id, portfolio_id, ticker, shares, buy_price, buy_date
            FROM holdings;
            DROP TABLE holdings;
            ALTER TABLE holdings_upgraded RENAME TO holdings;
            COMMIT;
            """
        )

    @property
    def default_portfolio_id(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM portfolios WHERE name = ?",
                ("My Portfolio",),
            ).fetchone()
        if row is None:
            raise RuntimeError("The default portfolio could not be found.")
        return int(row["id"])

    def list_holdings(self, portfolio_id: int) -> list[Holding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, portfolio_id, ticker, shares, buy_price, buy_date
                FROM holdings
                WHERE portfolio_id = ?
                ORDER BY ticker, id
                """,
                (portfolio_id,),
            ).fetchall()
        return [self._to_holding(row) for row in rows]

    def add_holding(
        self,
        portfolio_id: int,
        ticker: str,
        shares: float,
        buy_price: float,
        buy_date: str | None,
    ) -> int:
        values = validate_holding(ticker, shares, buy_price, buy_date)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO holdings (portfolio_id, ticker, shares, buy_price, buy_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (portfolio_id, *values),
            )
        return int(cursor.lastrowid)

    def update_holding(
        self,
        holding_id: int,
        portfolio_id: int,
        ticker: str,
        shares: float,
        buy_price: float,
        buy_date: str | None,
    ) -> None:
        values = validate_holding(ticker, shares, buy_price, buy_date)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE holdings
                SET ticker = ?, shares = ?, buy_price = ?, buy_date = ?
                WHERE id = ? AND portfolio_id = ?
                """,
                (*values, holding_id, portfolio_id),
            )
        if cursor.rowcount == 0:
            raise LookupError("The selected holding no longer exists.")

    def delete_holding(self, holding_id: int, portfolio_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM holdings WHERE id = ? AND portfolio_id = ?",
                (holding_id, portfolio_id),
            )
        if cursor.rowcount == 0:
            raise LookupError("The selected holding no longer exists.")

    def get_cached_prices(self) -> dict[str, CachedPrice]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker, price, fetched_at FROM price_cache"
            ).fetchall()
        return {
            str(row["ticker"]): CachedPrice(
                ticker=str(row["ticker"]),
                price=float(row["price"]),
                fetched_at=str(row["fetched_at"]),
            )
            for row in rows
        }

    def save_prices(self, prices: dict[str, float]) -> None:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        normalized: list[tuple[str, float, str]] = []
        for ticker, price in prices.items():
            normalized_ticker = ticker.strip().upper()
            numeric_price = float(price)
            if not normalized_ticker:
                raise ValueError("Ticker symbols cannot be blank.")
            if not math.isfinite(numeric_price) or numeric_price <= 0:
                raise ValueError(
                    f"Price for {normalized_ticker} must be greater than zero."
                )
            normalized.append((normalized_ticker, numeric_price, fetched_at))

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO price_cache (ticker, price, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    price = excluded.price,
                    fetched_at = excluded.fetched_at
                """,
                normalized,
            )

    def get_cached_sectors(self) -> dict[str, CachedSector]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker, sector, fetched_at FROM sector_cache"
            ).fetchall()
        return {
            str(row["ticker"]): CachedSector(
                ticker=str(row["ticker"]),
                sector=str(row["sector"]),
                fetched_at=str(row["fetched_at"]),
            )
            for row in rows
        }

    def save_sectors(self, sectors: dict[str, str]) -> None:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        normalized: list[tuple[str, str, str]] = []
        for ticker, sector in sectors.items():
            normalized_ticker = ticker.strip().upper()
            normalized_sector = sector.strip()
            if not normalized_ticker or not normalized_sector:
                raise ValueError("Ticker and sector cannot be blank.")
            normalized.append((normalized_ticker, normalized_sector, fetched_at))

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO sector_cache (ticker, sector, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    sector = excluded.sector,
                    fetched_at = excluded.fetched_at
                """,
                normalized,
            )

    def tickers_needing_sector(
        self, tickers: list[str], max_age: timedelta = timedelta(days=1)
    ) -> list[str]:
        """Tickers with no saved sector, or one older than ``max_age``."""
        cached = self.get_cached_sectors()
        cutoff = datetime.now(timezone.utc) - max_age
        return [
            ticker
            for ticker in tickers
            if ticker not in cached
            or datetime.fromisoformat(cached[ticker].fetched_at) < cutoff
        ]

    def get_price_history(self) -> dict[str, dict[str, float]]:
        return self._daily_series("SELECT ticker, date, close FROM price_history")

    def get_split_history(self) -> dict[str, dict[str, float]]:
        return self._daily_series("SELECT ticker, date, ratio FROM split_history")

    def get_dividend_history(self) -> dict[str, dict[str, float]]:
        """Dividend per share by ex-dividend date, as reported by Yahoo."""
        return self._daily_series(
            "SELECT ticker, date, per_share FROM dividend_history"
        )

    def list_manual_dividends(self, portfolio_id: int) -> list[ManualDividend]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, portfolio_id, ticker, date, amount
                FROM dividends
                WHERE portfolio_id = ?
                ORDER BY date DESC, ticker
                """,
                (portfolio_id,),
            ).fetchall()
        return [
            ManualDividend(
                id=int(row["id"]),
                portfolio_id=int(row["portfolio_id"]),
                ticker=str(row["ticker"]),
                date=str(row["date"]),
                amount=float(row["amount"]),
            )
            for row in rows
        ]

    def save_manual_dividend(
        self,
        portfolio_id: int,
        ticker: str,
        dividend_date: str,
        amount: float,
        dividend_id: int | None = None,
    ) -> None:
        """Add a dividend, or change the one with ``dividend_id``.

        Saving for a ticker and date that already has an entry updates it.
        An amount of $0 records that an estimated dividend wasn't received.
        """
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise ValueError("Enter a ticker symbol.")
        try:
            parsed_date = date.fromisoformat(dividend_date).isoformat()
        except ValueError as error:
            raise ValueError("Enter a valid dividend date.") from error
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Dividend amount can't be negative.")

        with self._connect() as connection:
            if dividend_id is not None:
                connection.execute(
                    "DELETE FROM dividends WHERE id = ? AND portfolio_id = ?",
                    (dividend_id, portfolio_id),
                )
            connection.execute(
                """
                INSERT INTO dividends (portfolio_id, ticker, date, amount)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(portfolio_id, ticker, date) DO UPDATE SET
                    amount = excluded.amount
                """,
                (portfolio_id, normalized_ticker, parsed_date, amount),
            )

    def delete_manual_dividend(self, dividend_id: int, portfolio_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM dividends WHERE id = ? AND portfolio_id = ?",
                (dividend_id, portfolio_id),
            )
        if cursor.rowcount == 0:
            raise LookupError("The selected dividend no longer exists.")

    def save_price_history(
        self,
        ticker: str,
        start_date: str,
        closes: dict[str, float],
        splits: dict[str, float],
        dividends: dict[str, float] | None = None,
    ) -> None:
        """Replace a ticker's saved history with a fresh download.

        The whole range is replaced, not appended, because Yahoo re-adjusts
        older prices after a split.
        """
        normalized_ticker = ticker.strip().upper()
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        dividends = dividends or {}
        for value in (*closes.values(), *splits.values(), *dividends.values()):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    f"History for {normalized_ticker} has an invalid value."
                )
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM price_history WHERE ticker = ?", (normalized_ticker,)
            )
            connection.execute(
                "DELETE FROM split_history WHERE ticker = ?", (normalized_ticker,)
            )
            connection.execute(
                "DELETE FROM dividend_history WHERE ticker = ?", (normalized_ticker,)
            )
            connection.executemany(
                """
                INSERT INTO dividend_history (ticker, date, per_share)
                VALUES (?, ?, ?)
                """,
                [(normalized_ticker, day, value) for day, value in dividends.items()],
            )
            connection.executemany(
                "INSERT INTO price_history (ticker, date, close) VALUES (?, ?, ?)",
                [(normalized_ticker, day, close) for day, close in closes.items()],
            )
            connection.executemany(
                "INSERT INTO split_history (ticker, date, ratio) VALUES (?, ?, ?)",
                [(normalized_ticker, day, ratio) for day, ratio in splits.items()],
            )
            connection.execute(
                """
                INSERT INTO history_fetches (ticker, start_date, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    start_date = excluded.start_date,
                    fetched_at = excluded.fetched_at
                """,
                (normalized_ticker, start_date, fetched_at),
            )

    def history_needing_refresh(
        self,
        start_dates: dict[str, str],
        max_age: timedelta = timedelta(days=1),
    ) -> dict[str, str]:
        """Tickers whose history is missing, older than ``max_age``, or
        doesn't reach back to the earliest buy date. Maps ticker -> start date.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker, start_date, fetched_at FROM history_fetches"
            ).fetchall()
        fetches = {str(row["ticker"]): row for row in rows}
        cutoff = datetime.now(timezone.utc) - max_age
        needed: dict[str, str] = {}
        for ticker, start_date in start_dates.items():
            fetch = fetches.get(ticker)
            if (
                fetch is None
                or str(fetch["start_date"]) > start_date
                or datetime.fromisoformat(str(fetch["fetched_at"])) < cutoff
            ):
                needed[ticker] = start_date
        return needed

    def _daily_series(self, query: str) -> dict[str, dict[str, float]]:
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        series: dict[str, dict[str, float]] = {}
        for ticker, day, value in rows:
            series.setdefault(str(ticker), {})[str(day)] = float(value)
        return series

    def import_holdings(
        self,
        portfolio_id: int,
        holdings: Iterable[NewHolding],
        replace_existing: bool,
    ) -> int:
        """Save many holdings at once; all are saved or none are.

        With ``replace_existing``, the portfolio's current holdings are deleted
        first, in the same step.
        """
        rows = [
            (
                portfolio_id,
                *validate_holding(
                    holding.ticker, holding.shares, holding.buy_price, holding.buy_date
                ),
            )
            for holding in holdings
        ]
        with self._connect() as connection:
            if replace_existing:
                connection.execute(
                    "DELETE FROM holdings WHERE portfolio_id = ?", (portfolio_id,)
                )
            connection.executemany(
                """
                INSERT INTO holdings (portfolio_id, ticker, shares, buy_price, buy_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    @staticmethod
    def _to_holding(row: sqlite3.Row) -> Holding:
        return Holding(
            id=int(row["id"]),
            portfolio_id=int(row["portfolio_id"]),
            ticker=str(row["ticker"]),
            shares=float(row["shares"]),
            buy_price=float(row["buy_price"]),
            buy_date=None if row["buy_date"] is None else str(row["buy_date"]),
        )
