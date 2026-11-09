"""Tests for estimated and manual dividends."""
import pytest

from portfolio_app.db.holdings import Holding, HoldingRepository, ManualDividend
from portfolio_app.services.dividends import (
    DividendEntry,
    combine_dividends,
    estimate_dividends,
    totals_by_year,
)
from portfolio_app.services.history import missing_date_note


def holding(ticker, shares, buy_date, holding_id=1):
    return Holding(holding_id, 1, ticker, shares, 50, buy_date)


def manual(ticker, date, amount, dividend_id=1):
    return ManualDividend(dividend_id, 1, ticker, date, amount)


@pytest.fixture
def repository(tmp_path):
    return HoldingRepository(tmp_path / "portfolio.db")


def test_estimate_is_shares_times_dividend_per_share():
    history = {"KO": {"2026-03-13": 0.53, "2026-06-15": 0.53}}

    result = estimate_dividends([holding("KO", 50, "2026-01-05")], history)

    assert result == [
        DividendEntry("KO", "2026-03-13", 50, 0.53, pytest.approx(26.5), "Estimated"),
        DividendEntry("KO", "2026-06-15", 50, 0.53, pytest.approx(26.5), "Estimated"),
    ]


def test_buying_on_or_after_ex_date_does_not_qualify():
    history = {"KO": {"2026-03-13": 0.53}}

    bought_day_before = estimate_dividends([holding("KO", 10, "2026-03-12")], history)
    bought_on_ex_date = estimate_dividends([holding("KO", 10, "2026-03-13")], history)
    bought_after = estimate_dividends([holding("KO", 10, "2026-03-20")], history)

    assert [entry.amount for entry in bought_day_before] == [pytest.approx(5.3)]
    assert bought_on_ex_date == []
    assert bought_after == []


def test_multiple_buys_count_only_shares_held_before_each_ex_date():
    history = {"KO": {"2026-03-13": 0.50, "2026-06-15": 0.50}}
    holdings = [
        holding("KO", 10, "2026-01-05", 1),
        holding("KO", 30, "2026-04-01", 2),  # only in time for June
    ]

    result = estimate_dividends(holdings, history)

    assert [(e.date, e.shares, e.amount) for e in result] == [
        ("2026-03-13", 10, 5.0),
        ("2026-06-15", 40, 20.0),
    ]


def test_holdings_without_a_buy_date_are_left_out():
    history = {"KO": {"2026-03-13": 0.53}, "T": {"2026-04-09": 0.2775}}
    holdings = [holding("KO", 10, "2026-01-05", 1), holding("T", 100, None, 2)]

    result = estimate_dividends(holdings, history)

    assert [entry.ticker for entry in result] == ["KO"]
    assert missing_date_note([holdings[1]]) == (
        "1 holding left out: buy date missing (T)."
    )


def test_missing_date_note_counts_holdings():
    undated = [holding(t, 1, None, i) for i, t in enumerate("ABCDEF")]

    assert missing_date_note(undated) == (
        "6 holdings left out: buy date missing (A, B, C, D, E, F)."
    )


def test_manual_entry_replaces_estimate_for_same_ticker_and_date():
    estimated = estimate_dividends(
        [holding("KO", 50, "2026-01-05")], {"KO": {"2026-03-13": 0.53}}
    )

    result = combine_dividends(estimated, [manual("KO", "2026-03-13", 25.00, 7)])

    assert result == [
        DividendEntry("KO", "2026-03-13", 50, 0.5, 25.00, "Manual", manual_id=7)
    ]


def test_manual_entries_are_added_and_log_is_newest_first():
    estimated = estimate_dividends(
        [holding("KO", 10, "2026-01-05")], {"KO": {"2026-03-13": 0.50}}
    )

    result = combine_dividends(
        estimated,
        [manual("NEWFX", "2025-12-18", 48.5, 1), manual("T", "2026-07-01", 2.71, 2)],
    )

    assert [(e.date, e.ticker, e.source) for e in result] == [
        ("2026-07-01", "T", "Manual"),
        ("2026-03-13", "KO", "Estimated"),
        ("2025-12-18", "NEWFX", "Manual"),
    ]
    assert result[0].shares is None  # no holding data behind a pure manual entry


def test_zero_manual_entry_marks_estimate_not_received():
    estimated = estimate_dividends(
        [holding("KO", 10, "2026-01-05")], {"KO": {"2026-03-13": 0.50}}
    )

    result = combine_dividends(estimated, [manual("KO", "2026-03-13", 0)])

    assert [(e.amount, e.source) for e in result] == [(0, "Manual")]
    assert totals_by_year(result) == {"2026": 0}


def test_totals_by_year_newest_first():
    entries = [
        DividendEntry("KO", "2026-03-13", 10, 0.5, 5.0, "Estimated"),
        DividendEntry("KO", "2025-12-01", 10, 0.5, 5.0, "Estimated"),
        DividendEntry("T", "2026-07-01", None, None, 2.5, "Manual"),
    ]

    assert totals_by_year(entries) == {"2026": 7.5, "2025": 5.0}
    assert list(totals_by_year(entries)) == ["2026", "2025"]
    assert totals_by_year([]) == {}


def test_manual_dividends_are_saved_edited_and_deleted(repository):
    portfolio_id = repository.default_portfolio_id

    repository.save_manual_dividend(portfolio_id, " ko ", "2026-03-13", 26.5)
    repository.save_manual_dividend(portfolio_id, "KO", "2026-03-13", 25.0)  # same key
    saved = repository.list_manual_dividends(portfolio_id)
    assert [(d.ticker, d.date, d.amount) for d in saved] == [("KO", "2026-03-13", 25.0)]

    repository.save_manual_dividend(
        portfolio_id, "KO", "2026-03-16", 25.0, dividend_id=saved[0].id
    )
    moved = repository.list_manual_dividends(portfolio_id)
    assert [(d.ticker, d.date) for d in moved] == [("KO", "2026-03-16")]

    repository.delete_manual_dividend(moved[0].id, portfolio_id)
    assert repository.list_manual_dividends(portfolio_id) == []


def test_invalid_manual_dividends_are_rejected(repository):
    portfolio_id = repository.default_portfolio_id

    with pytest.raises(ValueError):
        repository.save_manual_dividend(portfolio_id, "KO", "2026-03-13", -1)
    with pytest.raises(ValueError):
        repository.save_manual_dividend(portfolio_id, "", "2026-03-13", 1)
    with pytest.raises(ValueError):
        repository.save_manual_dividend(portfolio_id, "KO", "not a date", 1)


def test_dividend_history_is_saved_with_price_history(repository):
    repository.save_price_history(
        "KO", "2026-01-02", {"2026-03-13": 77.34}, {}, {"2026-03-13": 0.53}
    )

    assert repository.get_dividend_history() == {"KO": {"2026-03-13": 0.53}}


def test_history_saved_before_dividends_existed_is_downloaded_again(tmp_path):
    import sqlite3

    path = tmp_path / "portfolio.db"
    HoldingRepository(path).save_price_history("KO", "2026-01-02", {"2026-03-13": 77}, {})
    with sqlite3.connect(path) as connection:  # simulate an older database
        connection.execute("DROP TABLE dividend_history")
    connection.close()

    reopened = HoldingRepository(path)

    assert reopened.history_needing_refresh({"KO": "2026-01-02"}) == {"KO": "2026-01-02"}
    # Only once: opening again doesn't force another download.
    reopened.save_price_history("KO", "2026-01-02", {"2026-03-13": 77}, {}, {})
    assert HoldingRepository(path).history_needing_refresh({"KO": "2026-01-02"}) == {}
