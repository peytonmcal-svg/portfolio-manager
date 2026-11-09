"""The main application window."""
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from PySide6.QtCore import QDate, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from portfolio_app.config import APP_NAME, DATA_DIR
from portfolio_app.db.holdings import Holding, HoldingRepository
from portfolio_app.services.allocation import (
    allocation_by_holding,
    allocation_by_sector,
)
from portfolio_app.services.csv_import import CsvImportError, read_holdings_csv
from portfolio_app.services.history import (
    BENCHMARK_TICKER,
    Comparison,
    calculate_benchmark_history,
    calculate_value_history,
    compare_to_benchmark,
    split_by_buy_date,
    tickers_split_after_buy,
    tickers_without_history,
)
from portfolio_app.services.market_data import (
    calculate_holdings_values,
    calculate_portfolio_value,
    fetch_current_price,
    fetch_price_history,
    fetch_sector,
)
from portfolio_app.ui.allocation_chart import AllocationChart
from portfolio_app.ui.value_history_chart import ValueHistoryChart


@dataclass
class RefreshResult:
    prices: dict[str, float] = field(default_factory=dict)
    price_errors: list[str] = field(default_factory=list)
    sectors: dict[str, str] = field(default_factory=dict)
    sector_errors: list[str] = field(default_factory=list)
    # ticker -> (start date, daily closes, splits)
    histories: dict[str, tuple[str, dict[str, float], dict[str, float]]] = field(
        default_factory=dict
    )
    history_errors: list[str] = field(default_factory=list)


DATE_MISSING = "Date missing"


class PriceRefreshSignals(QObject):
    completed = Signal(object)


class PriceRefreshTask(QRunnable):
    """Fetch prices for every ticker; sectors and history only where stale."""

    def __init__(
        self,
        tickers: list[str],
        sector_tickers: list[str],
        history_starts: dict[str, str],
    ) -> None:
        super().__init__()
        self.tickers = tickers
        self.sector_tickers = sector_tickers
        self.history_starts = history_starts
        self.signals = PriceRefreshSignals()

    def run(self) -> None:
        result = RefreshResult()
        for ticker in self.tickers:
            try:
                result.prices[ticker] = fetch_current_price(ticker)
            except Exception:
                result.price_errors.append(ticker)
        for ticker in self.sector_tickers:
            try:
                result.sectors[ticker] = fetch_sector(ticker)
            except Exception:
                result.sector_errors.append(ticker)
        for ticker, start_date in self.history_starts.items():
            try:
                closes, splits = fetch_price_history(ticker, start_date)
                result.histories[ticker] = (start_date, closes, splits)
            except Exception:
                result.history_errors.append(ticker)
        self.signals.completed.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 700)
        self.repository = HoldingRepository()
        self.portfolio_id = self.repository.default_portfolio_id
        self.selected_holding_id: int | None = None
        self.price_task: PriceRefreshTask | None = None
        self.price_thread_pool = QThreadPool.globalInstance()

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        form = QFormLayout()
        self.ticker_input = QLineEdit()
        self.ticker_input.setMaxLength(15)
        self.shares_input = QDoubleSpinBox()
        self.shares_input.setDecimals(6)
        self.shares_input.setRange(0, 1_000_000_000)
        self.buy_price_input = QDoubleSpinBox()
        self.buy_price_input.setDecimals(4)
        self.buy_price_input.setRange(0, 1_000_000_000)
        self.buy_date_input = QDateEdit()
        self.buy_date_input.setCalendarPopup(True)
        self.buy_date_input.setDisplayFormat("yyyy-MM-dd")
        self.buy_date_input.setDate(QDate.currentDate())
        self.date_missing_input = QCheckBox("Date missing")
        self.date_missing_input.toggled.connect(
            lambda missing: self.buy_date_input.setEnabled(not missing)
        )
        buy_date_row = QHBoxLayout()
        buy_date_row.addWidget(self.buy_date_input, stretch=1)
        buy_date_row.addWidget(self.date_missing_input)
        form.addRow("Ticker", self.ticker_input)
        form.addRow("Shares", self.shares_input)
        form.addRow("Buy price ($)", self.buy_price_input)
        form.addRow("Buy date", buy_date_row)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("Add holding")
        self.cancel_button = QPushButton("Cancel")
        self.delete_button = QPushButton("Delete selected")
        self.refresh_prices_button = QPushButton("Refresh prices")
        self.import_button = QPushButton("Import from CSV…")
        self.import_button.clicked.connect(self._import_csv)
        self.cancel_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_holding)
        self.cancel_button.clicked.connect(self._clear_form)
        self.delete_button.clicked.connect(self._delete_holding)
        self.refresh_prices_button.clicked.connect(self._refresh_prices)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.refresh_prices_button)
        buttons.addWidget(self.import_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.holdings_table = QTableWidget(0, 9)
        self.holdings_table.setHorizontalHeaderLabels(
            [
                "Ticker",
                "Shares",
                "Buy price ($)",
                "Buy date",
                "Current price ($)",
                "Cost basis ($)",
                "Market value ($)",
                "Gain/loss ($)",
                "Gain/loss (%)",
            ]
        )
        self.holdings_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.holdings_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.holdings_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.holdings_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.holdings_table.itemSelectionChanged.connect(self._selection_changed)

        allocation_tab = QWidget()
        allocation_layout = QHBoxLayout(allocation_tab)
        self.holding_chart = AllocationChart("By holding")
        self.sector_chart = AllocationChart("By sector")
        allocation_layout.addWidget(self.holding_chart)
        allocation_layout.addWidget(self.sector_chart)

        performance_tab = QWidget()
        performance_layout = QVBoxLayout(performance_tab)
        self.comparison_summary = QLabel()
        summary_font = self.comparison_summary.font()
        summary_font.setPointSizeF(summary_font.pointSizeF() * 1.2)
        self.comparison_summary.setFont(summary_font)
        self.value_history_chart = ValueHistoryChart()
        self.history_status = QLabel()
        self.history_status.setWordWrap(True)
        performance_layout.addWidget(self.comparison_summary)
        performance_layout.addWidget(self.value_history_chart)
        performance_layout.addWidget(self.history_status)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.holdings_table, "Holdings")
        self.tabs.addTab(allocation_tab, "Allocation")
        self.tabs.addTab(performance_tab, "Performance")
        layout.addWidget(self.tabs)

        self.price_status = QLabel()
        layout.addWidget(self.price_status)
        self.setCentralWidget(central_widget)
        self._reload_holdings()

    def _reload_holdings(self) -> None:
        holdings = self.repository.list_holdings(self.portfolio_id)
        cached_prices = self.repository.get_cached_prices()
        prices = {ticker: quote.price for ticker, quote in cached_prices.items()}
        positions = calculate_holdings_values(holdings, prices)
        total = calculate_portfolio_value(positions)
        self.holdings_table.setRowCount(len(holdings) + 1)
        for row, (holding, position) in enumerate(zip(holdings, positions)):
            self.holdings_table.setItem(row, 0, self._table_item(holding.ticker))
            self.holdings_table.setItem(
                row, 1, self._table_item(self._format_number(holding.shares))
            )
            self.holdings_table.setItem(
                row,
                2,
                self._table_item(
                    f"{holding.buy_price:.4f}".rstrip("0").rstrip(".")
                ),
            )
            self.holdings_table.setItem(
                row, 3, self._table_item(holding.buy_date or DATE_MISSING)
            )
            values = (
                self._format_currency(position.current_price),
                self._format_currency(position.cost_basis),
                self._format_currency(position.market_value),
                self._format_currency(position.gain_loss, signed=True),
                self._format_percent(position.gain_loss_percent),
            )
            for column, value in enumerate(values, start=4):
                self.holdings_table.setItem(row, column, self._table_item(value))
            self.holdings_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, holding.id
            )

        total_row = len(holdings)
        total_values = (
            "TOTAL",
            "",
            "",
            "",
            "",
            self._format_currency(total.cost_basis),
            self._format_currency(total.market_value),
            self._format_currency(total.gain_loss, signed=True),
            self._format_percent(total.gain_loss_percent),
        )
        for column, value in enumerate(total_values):
            item = self._table_item(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.holdings_table.setItem(total_row, column, item)

        no_prices_message = (
            "No priced holdings yet.\nChoose “Refresh prices” to see allocation."
        )
        self.holding_chart.set_slices(
            allocation_by_holding(positions), no_prices_message
        )
        sectors = {
            ticker: cached.sector
            for ticker, cached in self.repository.get_cached_sectors().items()
        }
        self.sector_chart.set_slices(
            allocation_by_sector(positions, sectors), no_prices_message
        )
        self._reload_value_history(holdings)

        missing_tickers = sorted(
            {
                position.ticker
                for position in positions
                if position.current_price is None
            }
        )
        if not cached_prices:
            self.price_status.setText(
                "No saved prices yet. Choose “Refresh prices” to get the latest values."
            )
        elif missing_tickers:
            self.price_status.setText(
                "Some prices are unavailable. Portfolio totals include priced holdings "
                "only; choose “Refresh prices” to try again."
            )
        else:
            latest_update = max(
                quote.fetched_at for quote in cached_prices.values()
            )
            self.price_status.setText(
                f"Showing saved prices as of {latest_update.replace('T', ' ')}. "
                "Choose “Refresh prices” to update."
            )

    def _reload_value_history(self, holdings: list[Holding]) -> None:
        price_history = self.repository.get_price_history()
        dated, undated = split_by_buy_date(holdings)
        missing = tickers_without_history(dated, price_history)
        # The SPY comparison uses exactly the holdings the portfolio line uses.
        tracked = [holding for holding in dated if holding.ticker not in missing]
        points = calculate_value_history(tracked, price_history)
        benchmark_points = calculate_benchmark_history(
            tracked, price_history.get(BENCHMARK_TICKER, {})
        )
        if holdings and not dated:
            empty_message = (
                "No holdings have a buy date yet.\n"
                "Add buy dates on the Holdings tab to build this chart."
            )
        else:
            empty_message = (
                "No price history yet.\nChoose “Refresh prices” to build the chart."
            )
        self.value_history_chart.set_points(points, benchmark_points, empty_message)
        self._show_comparison(compare_to_benchmark(points, benchmark_points))

        messages = []
        if undated:
            undated_tickers = sorted({holding.ticker for holding in undated})
            messages.append(
                f"Date missing for: {', '.join(undated_tickers)}. These holdings "
                "are left out of this chart and the "
                f"{BENCHMARK_TICKER} comparison until a buy date is added "
                "(select one on the Holdings tab to edit it)."
            )
        if price_history and missing:
            messages.append(
                f"No price history for: {', '.join(missing)}. These holdings are "
                "left out of the chart (value, money invested, and the "
                f"{BENCHMARK_TICKER} comparison)."
            )
        if points and not benchmark_points:
            messages.append(
                f"No {BENCHMARK_TICKER} price history yet, so the comparison line "
                "is hidden. Choose “Refresh prices” to try again."
            )
        split = tickers_split_after_buy(dated, self.repository.get_split_history())
        if split:
            messages.append(
                f"⚠ {', '.join(split)} had a stock split after your buy date. "
                "Past prices are split-adjusted, so check that shares and buy "
                "price are entered as post-split numbers (e.g. 2-for-1: double "
                "the shares, halve the price). If they already are, no change "
                "is needed."
            )
        if not messages:
            messages.append(
                "Value uses each day’s closing price and excludes dividends. "
                f"The {BENCHMARK_TICKER} line puts each buy’s cost into "
                f"{BENCHMARK_TICKER} on the same date. Assumes no shares have "
                "been sold."
            )
        self.history_status.setText("\n".join(messages))

    def _show_comparison(self, comparison: Comparison | None) -> None:
        if comparison is None:
            self.comparison_summary.setText("")
            return
        self.comparison_summary.setText(
            f"Your portfolio: {self._format_percent(comparison.portfolio_return_percent)} "
            f"({self._format_currency(comparison.portfolio_value)})   ·   "
            f"{BENCHMARK_TICKER}: "
            f"{self._format_percent(comparison.benchmark_return_percent)} "
            f"({self._format_currency(comparison.benchmark_value)})   ·   "
            f"on {self._format_currency(comparison.invested)} invested, "
            f"as of {comparison.date}"
        )

    @staticmethod
    def _table_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_currency(value: float | None, signed: bool = False) -> str:
        if value is None:
            return "—"
        if value < 0:
            return f"-${abs(value):,.2f}"
        sign = "+" if signed and value > 0 else ""
        return f"{sign}${value:,.2f}"

    @staticmethod
    def _format_percent(value: float | None) -> str:
        if value is None:
            return "—"
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.2f}%"

    def _refresh_prices(self) -> None:
        holdings = self.repository.list_holdings(self.portfolio_id)
        tickers = sorted({holding.ticker for holding in holdings})
        if not tickers:
            self.price_status.setText("Add holdings before refreshing prices.")
            return
        self.refresh_prices_button.setEnabled(False)
        self.price_status.setText("Getting latest prices from Yahoo Finance…")
        sector_tickers = self.repository.tickers_needing_sector(tickers)
        dated, _ = split_by_buy_date(holdings)
        earliest_buy: dict[str, str] = {}
        for holding in dated:
            current = earliest_buy.get(holding.ticker, holding.buy_date)
            earliest_buy[holding.ticker] = min(current, holding.buy_date)
        if dated:
            # SPY history is needed from the first buy of any holding.
            first_buy = min(holding.buy_date for holding in dated)
            earliest_buy[BENCHMARK_TICKER] = min(
                earliest_buy.get(BENCHMARK_TICKER, first_buy), first_buy
            )
        history_starts = self.repository.history_needing_refresh(earliest_buy)
        self.price_task = PriceRefreshTask(tickers, sector_tickers, history_starts)
        self.price_task.signals.completed.connect(self._prices_refreshed)
        self.price_thread_pool.start(self.price_task)

    def _prices_refreshed(self, result: RefreshResult) -> None:
        self.refresh_prices_button.setEnabled(True)
        self.price_task = None
        try:
            self.repository.save_prices(result.prices)
            self.repository.save_sectors(result.sectors)
            for ticker, (start_date, closes, splits) in result.histories.items():
                self.repository.save_price_history(
                    ticker, start_date, closes, splits
                )
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.critical(
                self, "Price cache error", f"Prices could not be saved:\n{error}"
            )
            self._reload_holdings()
            return

        self._reload_holdings()
        if result.price_errors:
            failed_tickers = ", ".join(sorted(result.price_errors))
            self.price_status.setText(
                f"Could not refresh: {failed_tickers}. Showing saved prices where "
                "available; totals exclude holdings without a saved price."
            )
        else:
            self.price_status.setText(
                "Prices refreshed successfully from Yahoo Finance."
            )
        if result.sector_errors:
            self.price_status.setText(
                f"{self.price_status.text()} Sector unavailable for: "
                f"{', '.join(sorted(result.sector_errors))} (shown as last saved "
                "or “Unknown”)."
            )
        if result.history_errors:
            self.price_status.setText(
                f"{self.price_status.text()} Price history unavailable for: "
                f"{', '.join(sorted(result.history_errors))} (showing last saved "
                "history)."
            )

    def _selection_changed(self) -> None:
        selected = self.holdings_table.selectedItems()
        if not selected:
            self.selected_holding_id = None
            self.save_button.setText("Add holding")
            self.cancel_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        holding_id = selected[0].data(Qt.ItemDataRole.UserRole)
        if holding_id is None:
            self.holdings_table.clearSelection()
            return
        self.selected_holding_id = int(holding_id)
        holding = next(
            item
            for item in self.repository.list_holdings(self.portfolio_id)
            if item.id == self.selected_holding_id
        )
        self.ticker_input.setText(holding.ticker)
        self.shares_input.setValue(holding.shares)
        self.buy_price_input.setValue(holding.buy_price)
        self.date_missing_input.setChecked(holding.buy_date is None)
        if holding.buy_date is None:
            self.buy_date_input.setDate(QDate.currentDate())
        else:
            year, month, day = map(int, holding.buy_date.split("-"))
            self.buy_date_input.setDate(QDate(year, month, day))
        self.save_button.setText("Save changes")
        self.cancel_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def _save_holding(self) -> None:
        try:
            values = (
                self.ticker_input.text(),
                self.shares_input.value(),
                self.buy_price_input.value(),
                None
                if self.date_missing_input.isChecked()
                else self.buy_date_input.date().toString("yyyy-MM-dd"),
            )
            if self.selected_holding_id is None:
                self.repository.add_holding(self.portfolio_id, *values)
            else:
                self.repository.update_holding(
                    self.selected_holding_id, self.portfolio_id, *values
                )
        except (ValueError, LookupError) as error:
            QMessageBox.warning(self, "Could not save holding", str(error))
            return
        except sqlite3.Error as error:
            QMessageBox.critical(
                self, "Database error", f"The holding could not be saved:\n{error}"
            )
            return

        self._clear_form()
        self._reload_holdings()

    def _delete_holding(self) -> None:
        if self.selected_holding_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete holding",
            "Delete the selected holding?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repository.delete_holding(
                self.selected_holding_id, self.portfolio_id
            )
        except LookupError as error:
            QMessageBox.warning(self, "Could not delete holding", str(error))
        except sqlite3.Error as error:
            QMessageBox.critical(
                self, "Database error", f"The holding could not be deleted:\n{error}"
            )
            return
        self._clear_form()
        self._reload_holdings()

    def _import_csv(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Import holdings from CSV",
            str(DATA_DIR),
            "CSV files (*.csv);;All files (*)",
        )
        if not file_name:
            return
        try:
            new_holdings = read_holdings_csv(Path(file_name))
        except CsvImportError as error:
            QMessageBox.warning(
                self,
                "Could not import file",
                "Nothing was imported. Please fix these problems and try again:"
                "\n\n" + "\n".join(error.problems[:15])
                + ("\n…" if len(error.problems) > 15 else ""),
            )
            return
        except OSError as error:
            QMessageBox.warning(self, "Could not open file", str(error))
            return

        existing_count = len(self.repository.list_holdings(self.portfolio_id))
        replace_existing = False
        if existing_count:
            question = QMessageBox(self)
            question.setWindowTitle("Import holdings")
            question.setText(
                f"Found {len(new_holdings)} holdings in the file. You already "
                f"have {existing_count} holding(s)."
            )
            question.setInformativeText(
                "Replace deletes your current holdings and keeps only the "
                "imported ones. Add keeps both."
            )
            replace = question.addButton(
                "Replace", QMessageBox.ButtonRole.DestructiveRole
            )
            add = question.addButton("Add", QMessageBox.ButtonRole.AcceptRole)
            question.addButton(QMessageBox.StandardButton.Cancel)
            question.exec()
            if question.clickedButton() not in (replace, add):
                return
            replace_existing = question.clickedButton() is replace
        try:
            count = self.repository.import_holdings(
                self.portfolio_id, new_holdings, replace_existing
            )
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.critical(
                self, "Import failed", f"Nothing was imported:\n{error}"
            )
            return

        self._clear_form()
        self._reload_holdings()
        undated = sum(1 for holding in new_holdings if holding.buy_date is None)
        message = f"Imported {count} holdings."
        if undated:
            message += f" {undated} have no buy date and are marked “{DATE_MISSING}”."
        self.price_status.setText(message + " Choose “Refresh prices” to update.")

    def _clear_form(self) -> None:
        self.holdings_table.clearSelection()
        self.selected_holding_id = None
        self.ticker_input.clear()
        self.shares_input.setValue(0)
        self.buy_price_input.setValue(0)
        self.buy_date_input.setDate(QDate.currentDate())
        self.date_missing_input.setChecked(False)
        self.save_button.setText("Add holding")
        self.cancel_button.setEnabled(False)
        self.delete_button.setEnabled(False)
