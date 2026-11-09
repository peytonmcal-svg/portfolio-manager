"""Tests for importing holdings from a CSV file."""
import sqlite3

import pytest

from portfolio_app.db.holdings import HoldingRepository, NewHolding
from portfolio_app.services.csv_import import CsvImportError, read_holdings_csv


@pytest.fixture
def repository(tmp_path):
    return HoldingRepository(tmp_path / "portfolio.db")


def write_csv(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "holdings.csv"
    path.write_text(text, encoding=encoding)
    return path


def test_reads_rows_with_blank_dates_and_mutual_funds(tmp_path):
    path = write_csv(
        tmp_path,
        "ticker,shares,buy_price,buy_date\n"
        "T,10.5,25.25,\n"
        "NEWFX,12.25,60.5,\n"
        "anefx,40.125,35.75,2024-03-01\n",
    )

    assert read_holdings_csv(path) == [
        NewHolding("T", 10.5, 25.25, None),
        NewHolding("NEWFX", 12.25, 60.5, None),
        NewHolding("ANEFX", 40.125, 35.75, "2024-03-01"),
    ]


def test_accepts_excel_style_files(tmp_path):
    path = write_csv(
        tmp_path,
        " Ticker , Shares , Buy Price , Buy Date \n"
        '"AAPL","1,200","$150.25",3/7/2024\n'
        "\n"
        "KO,5,60,\n",
        encoding="utf-8-sig",  # Excel's hidden byte-order mark
    )

    assert read_holdings_csv(path) == [
        NewHolding("AAPL", 1200, 150.25, "2024-03-07"),
        NewHolding("KO", 5, 60, None),
    ]


def test_buy_date_column_is_optional(tmp_path):
    path = write_csv(tmp_path, "ticker,shares,buy_price\nKO,5,60\n")

    assert read_holdings_csv(path) == [NewHolding("KO", 5, 60, None)]


def test_every_bad_row_is_reported_by_line_number(tmp_path):
    path = write_csv(
        tmp_path,
        "ticker,shares,buy_price,buy_date\n"
        "AAPL,1,100,\n"
        ",1,100,\n"
        "KO,abc,60,\n"
        "MSFT,1,0,\n"
        "SPY,1,400,next week\n",
    )

    with pytest.raises(CsvImportError) as error:
        read_holdings_csv(path)

    assert error.value.problems == [
        "Line 3: Enter a ticker symbol.",
        "Line 4: Shares must be a number (found “abc”).",
        "Line 5: Buy price must be greater than zero.",
        "Line 6: Buy date “next week” isn't a date (use YYYY-MM-DD).",
    ]


def test_missing_columns_and_empty_files_are_rejected(tmp_path):
    with pytest.raises(CsvImportError, match="Missing column"):
        read_holdings_csv(write_csv(tmp_path, "symbol,qty\nAAPL,1\n"))
    with pytest.raises(CsvImportError, match="no holdings"):
        read_holdings_csv(write_csv(tmp_path, "ticker,shares,buy_price,buy_date\n"))


def test_import_replace_deletes_old_holdings_and_saves_blank_dates(repository):
    portfolio_id = repository.default_portfolio_id
    repository.add_holding(portfolio_id, "ORCL", 3, 120.5, "2025-08-15")

    count = repository.import_holdings(
        portfolio_id,
        [NewHolding("NEWFX", 12.25, 60.5, None), NewHolding("T", 1, 30, None)],
        replace_existing=True,
    )

    holdings = repository.list_holdings(portfolio_id)
    assert count == 2
    assert [(h.ticker, h.buy_date) for h in holdings] == [("NEWFX", None), ("T", None)]


def test_import_add_keeps_existing_holdings(repository):
    portfolio_id = repository.default_portfolio_id
    repository.add_holding(portfolio_id, "ORCL", 3, 120.5, "2025-08-15")

    repository.import_holdings(
        portfolio_id, [NewHolding("T", 1, 30, None)], replace_existing=False
    )

    assert [h.ticker for h in repository.list_holdings(portfolio_id)] == ["ORCL", "T"]


def test_failed_import_changes_nothing(repository):
    portfolio_id = repository.default_portfolio_id
    repository.add_holding(portfolio_id, "ORCL", 3, 120.5, "2025-08-15")

    with pytest.raises(ValueError):
        repository.import_holdings(
            portfolio_id,
            [NewHolding("T", 1, 30, None), NewHolding("BAD", -1, 30, None)],
            replace_existing=True,
        )

    assert [h.ticker for h in repository.list_holdings(portfolio_id)] == ["ORCL"]


def test_blank_date_can_be_saved_and_edited(repository):
    portfolio_id = repository.default_portfolio_id
    holding_id = repository.add_holding(portfolio_id, "KO", 5, 60, "")

    assert repository.list_holdings(portfolio_id)[0].buy_date is None

    repository.update_holding(holding_id, portfolio_id, "KO", 5, 60, "2024-01-02")
    assert repository.list_holdings(portfolio_id)[0].buy_date == "2024-01-02"


def test_older_database_is_upgraded_to_allow_blank_dates(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE portfolios (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            INSERT INTO portfolios (name) VALUES ('My Portfolio');
            CREATE TABLE holdings (
                id INTEGER PRIMARY KEY,
                portfolio_id INTEGER NOT NULL REFERENCES portfolios(id)
                    ON DELETE CASCADE,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL CHECK (shares > 0),
                buy_price REAL NOT NULL CHECK (buy_price > 0),
                buy_date TEXT NOT NULL
            );
            INSERT INTO holdings (portfolio_id, ticker, shares, buy_price, buy_date)
            VALUES (1, 'ORCL', 3, 120.5, '2025-08-15');
            """
        )
    connection.close()

    repository = HoldingRepository(path)
    portfolio_id = repository.default_portfolio_id
    repository.add_holding(portfolio_id, "T", 1, 30, None)

    holdings = repository.list_holdings(portfolio_id)
    assert [(h.ticker, h.buy_date) for h in holdings] == [
        ("ORCL", "2025-08-15"),
        ("T", None),
    ]
