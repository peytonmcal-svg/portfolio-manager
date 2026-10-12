"""Tests for saving and managing holdings in SQLite."""
import sqlite3

import pytest

from portfolio_app.db.holdings import HoldingRepository


@pytest.fixture
def repository(tmp_path):
    return HoldingRepository(tmp_path / "portfolio.db")


def test_add_holding_normalizes_ticker_and_lists_by_portfolio(repository):
    portfolio_id = repository.default_portfolio_id

    holding_id = repository.add_holding(
        portfolio_id, "  aapl ", 2.5, 175.25, "2025-01-15"
    )

    holding = repository.list_holdings(portfolio_id)[0]
    assert holding.id == holding_id
    assert holding.portfolio_id == portfolio_id
    assert holding.ticker == "AAPL"
    assert holding.shares == 2.5
    assert holding.buy_price == 175.25
    assert holding.buy_date == "2025-01-15"


def test_holding_changes_persist_after_repository_reopens(tmp_path):
    database_path = tmp_path / "portfolio.db"
    repository = HoldingRepository(database_path)
    portfolio_id = repository.default_portfolio_id
    holding_id = repository.add_holding(
        portfolio_id, "MSFT", 3, 400, "2024-06-12"
    )

    reopened = HoldingRepository(database_path)

    assert reopened.list_holdings(portfolio_id)[0].id == holding_id


def test_price_cache_is_saved_and_reopened(tmp_path):
    database_path = tmp_path / "portfolio.db"
    repository = HoldingRepository(database_path)

    repository.save_prices({"aapl": 190.25})
    reopened = HoldingRepository(database_path)

    cached_price = reopened.get_cached_prices()["AAPL"]
    assert cached_price.ticker == "AAPL"
    assert cached_price.price == 190.25
    assert cached_price.fetched_at


def test_updating_price_cache_keeps_other_symbols(repository):
    repository.save_prices({"AAPL": 190, "MSFT": 400})

    repository.save_prices({"AAPL": 195})

    cached_prices = repository.get_cached_prices()
    assert cached_prices["AAPL"].price == 195
    assert cached_prices["MSFT"].price == 400


def test_update_and_delete_only_affect_the_selected_portfolio(repository):
    first_portfolio_id = repository.default_portfolio_id
    with sqlite3.connect(repository.database_path) as connection:
        second_portfolio_id = connection.execute(
            "INSERT INTO portfolios (name) VALUES (?)",
            ("Second Portfolio",),
        ).lastrowid

    holding_id = repository.add_holding(
        first_portfolio_id, "AAPL", 1, 100, "2025-01-01"
    )
    repository.add_holding(second_portfolio_id, "AAPL", 2, 110, "2025-02-01")

    repository.update_holding(
        holding_id, first_portfolio_id, "MSFT", 3, 200, "2025-03-01"
    )
    updated_holding = repository.list_holdings(first_portfolio_id)[0]
    assert updated_holding.ticker == "MSFT"
    assert updated_holding.shares == 3
    assert updated_holding.buy_price == 200
    assert updated_holding.buy_date == "2025-03-01"

    repository.delete_holding(holding_id, first_portfolio_id)

    assert repository.list_holdings(first_portfolio_id) == []
    assert repository.list_holdings(second_portfolio_id)[0].ticker == "AAPL"


@pytest.mark.parametrize(
    ("ticker", "shares", "buy_price", "buy_date"),
    [
        ("", 1, 10, "2025-01-01"),
        ("AAPL", 0, 10, "2025-01-01"),
        ("AAPL", 1, 0, "2025-01-01"),
        ("AAPL", 1, 10, "not-a-date"),
    ],
)
def test_rejects_invalid_holding_values(
    repository, ticker, shares, buy_price, buy_date
):
    with pytest.raises(ValueError):
        repository.add_holding(
            repository.default_portfolio_id, ticker, shares, buy_price, buy_date
        )
