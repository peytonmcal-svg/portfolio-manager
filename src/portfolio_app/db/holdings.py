"""SQLite storage for portfolios and their holdings."""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
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
    buy_date: str


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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolios (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS holdings (
                    id INTEGER PRIMARY KEY,
                    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id)
                        ON DELETE CASCADE,
                    ticker TEXT NOT NULL,
                    shares REAL NOT NULL CHECK (shares > 0),
                    buy_price REAL NOT NULL CHECK (buy_price > 0),
                    buy_date TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO portfolios (name) VALUES (?)",
                ("My Portfolio",),
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
        buy_date: str,
    ) -> int:
        values = self._validated_values(ticker, shares, buy_price, buy_date)
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
        buy_date: str,
    ) -> None:
        values = self._validated_values(ticker, shares, buy_price, buy_date)
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

    @staticmethod
    def _validated_values(
        ticker: str,
        shares: float,
        buy_price: float,
        buy_date: str,
    ) -> tuple[str, float, float, str]:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise ValueError("Enter a ticker symbol.")
        if not math.isfinite(shares) or shares <= 0:
            raise ValueError("Shares must be greater than zero.")
        if not math.isfinite(buy_price) or buy_price <= 0:
            raise ValueError("Buy price must be greater than zero.")
        try:
            parsed_date = date.fromisoformat(buy_date)
        except ValueError as error:
            raise ValueError("Enter a valid buy date.") from error
        return normalized_ticker, shares, buy_price, parsed_date.isoformat()

    @staticmethod
    def _to_holding(row: sqlite3.Row) -> Holding:
        return Holding(
            id=int(row["id"]),
            portfolio_id=int(row["portfolio_id"]),
            ticker=str(row["ticker"]),
            shares=float(row["shares"]),
            buy_price=float(row["buy_price"]),
            buy_date=str(row["buy_date"]),
        )
