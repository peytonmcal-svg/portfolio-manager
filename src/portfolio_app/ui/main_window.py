"""The main application window."""
import sqlite3

from PySide6.QtCore import QDate, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QDateEdit,
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
    QVBoxLayout,
    QWidget,
)

from portfolio_app.config import APP_NAME
from portfolio_app.db.holdings import HoldingRepository
from portfolio_app.services.market_data import (
    calculate_holdings_values,
    calculate_portfolio_value,
    fetch_current_price,
)


class PriceRefreshSignals(QObject):
    completed = Signal(object, object)


class PriceRefreshTask(QRunnable):
    def __init__(self, tickers: list[str]) -> None:
        super().__init__()
        self.tickers = tickers
        self.signals = PriceRefreshSignals()

    def run(self) -> None:
        prices: dict[str, float] = {}
        errors: dict[str, str] = {}
        for ticker in self.tickers:
            try:
                prices[ticker] = fetch_current_price(ticker)
            except Exception:
                errors[ticker] = "Yahoo Finance could not provide a current price."
        self.signals.completed.emit(prices, errors)


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
        form.addRow("Ticker", self.ticker_input)
        form.addRow("Shares", self.shares_input)
        form.addRow("Buy price ($)", self.buy_price_input)
        form.addRow("Buy date", self.buy_date_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("Add holding")
        self.cancel_button = QPushButton("Cancel")
        self.delete_button = QPushButton("Delete selected")
        self.refresh_prices_button = QPushButton("Refresh prices")
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
        layout.addWidget(self.holdings_table)

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
            self.holdings_table.setItem(row, 3, self._table_item(holding.buy_date))
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
        tickers = sorted(
            {
                holding.ticker
                for holding in self.repository.list_holdings(self.portfolio_id)
            }
        )
        if not tickers:
            self.price_status.setText("Add holdings before refreshing prices.")
            return
        self.refresh_prices_button.setEnabled(False)
        self.price_status.setText("Getting latest prices from Yahoo Finance…")
        self.price_task = PriceRefreshTask(tickers)
        self.price_task.signals.completed.connect(self._prices_refreshed)
        self.price_thread_pool.start(self.price_task)

    def _prices_refreshed(
        self, prices: dict[str, float], errors: dict[str, str]
    ) -> None:
        self.refresh_prices_button.setEnabled(True)
        self.price_task = None
        try:
            self.repository.save_prices(prices)
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.critical(
                self, "Price cache error", f"Prices could not be saved:\n{error}"
            )
            self._reload_holdings()
            return

        self._reload_holdings()
        if errors:
            failed_tickers = ", ".join(sorted(errors))
            self.price_status.setText(
                f"Could not refresh: {failed_tickers}. Showing saved prices where "
                "available; totals exclude holdings without a saved price."
            )
        else:
            self.price_status.setText(
                "Prices refreshed successfully from Yahoo Finance."
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
                self.buy_date_input.date().toString("yyyy-MM-dd"),
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

    def _clear_form(self) -> None:
        self.holdings_table.clearSelection()
        self.selected_holding_id = None
        self.ticker_input.clear()
        self.shares_input.setValue(0)
        self.buy_price_input.setValue(0)
        self.buy_date_input.setDate(QDate.currentDate())
        self.save_button.setText("Add holding")
        self.cancel_button.setEnabled(False)
        self.delete_button.setEnabled(False)
