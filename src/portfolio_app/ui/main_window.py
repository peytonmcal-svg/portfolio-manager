"""The main application window."""
import sqlite3

from PySide6.QtCore import QDate, Qt
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portfolio_app.config import APP_NAME
from portfolio_app.db.holdings import HoldingRepository


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 650)
        self.repository = HoldingRepository()
        self.portfolio_id = self.repository.default_portfolio_id
        self.selected_holding_id: int | None = None

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
        self.cancel_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_holding)
        self.cancel_button.clicked.connect(self._clear_form)
        self.delete_button.clicked.connect(self._delete_holding)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.holdings_table = QTableWidget(0, 4)
        self.holdings_table.setHorizontalHeaderLabels(
            ["Ticker", "Shares", "Buy price ($)", "Buy date"]
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

        self.setCentralWidget(central_widget)
        self._reload_holdings()

    def _reload_holdings(self) -> None:
        holdings = self.repository.list_holdings(self.portfolio_id)
        self.holdings_table.setRowCount(len(holdings))
        for row, holding in enumerate(holdings):
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
            self.holdings_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, holding.id
            )

    @staticmethod
    def _table_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _selection_changed(self) -> None:
        selected = self.holdings_table.selectedItems()
        if not selected:
            self.selected_holding_id = None
            self.save_button.setText("Add holding")
            self.cancel_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        holding_id = selected[0].data(Qt.ItemDataRole.UserRole)
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
