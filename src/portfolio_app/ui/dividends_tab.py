"""The Dividends tab: estimated and hand-entered dividend income."""
import sqlite3

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portfolio_app.db.holdings import Holding, HoldingRepository
from portfolio_app.services.dividends import (
    MANUAL,
    DividendEntry,
    combine_dividends,
    estimate_dividends,
    totals_by_year,
)
from portfolio_app.services.history import missing_date_note, split_by_buy_date


class DividendsTab(QWidget):
    def __init__(self, repository: HoldingRepository, portfolio_id: int) -> None:
        super().__init__()
        self.repository = repository
        self.portfolio_id = portfolio_id
        self.entries: list[DividendEntry] = []
        self.editing_manual_id: int | None = None
        layout = QVBoxLayout(self)

        self.totals_label = QLabel()
        font = self.totals_label.font()
        font.setPointSizeF(font.pointSizeF() * 1.2)
        self.totals_label.setFont(font)
        self.totals_label.setWordWrap(True)
        layout.addWidget(self.totals_label)

        form = QHBoxLayout()
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText("Ticker")
        self.ticker_input.setMaxLength(15)
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QDate.currentDate())
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setDecimals(2)
        self.amount_input.setRange(0, 1_000_000_000)
        self.amount_input.setPrefix("$")
        self.amount_input.setToolTip(
            "Total received. Enter $0 to mark an estimated dividend as not received."
        )
        self.save_button = QPushButton("Add dividend")
        self.delete_button = QPushButton("Delete manual entry")
        self.cancel_button = QPushButton("Cancel")
        self.delete_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.cancel_button.clicked.connect(self._clear_form)
        for label, widget in (
            ("Ticker", self.ticker_input),
            ("Date", self.date_input),
            ("Total amount", self.amount_input),
        ):
            form.addWidget(QLabel(label))
            form.addWidget(widget)
        form.addWidget(self.save_button)
        form.addWidget(self.delete_button)
        form.addWidget(self.cancel_button)
        form.addStretch()
        layout.addLayout(form)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Ticker", "Shares", "Per share ($)", "Amount ($)", "Source"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)

        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def reload(self, holdings: list[Holding]) -> None:
        estimated = estimate_dividends(
            holdings, self.repository.get_dividend_history()
        )
        manual = self.repository.list_manual_dividends(self.portfolio_id)
        self.entries = combine_dividends(estimated, manual)

        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            values = (
                entry.date,
                entry.ticker,
                "—" if entry.shares is None else f"{entry.shares:.6f}".rstrip("0").rstrip("."),
                "—" if entry.per_share is None else f"{entry.per_share:,.4f}",
                f"${entry.amount:,.2f}",
                entry.source,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

        totals = totals_by_year(self.entries)
        if totals:
            self.totals_label.setText(
                f"Total: ${sum(totals.values()):,.2f}   ·   "
                + "   ·   ".join(f"{year}: ${total:,.2f}" for year, total in totals.items())
            )
        else:
            self.totals_label.setText("No dividends yet.")

        dated, undated = split_by_buy_date(holdings)
        notes = []
        if undated:
            notes.append(missing_date_note(undated) + " Their dividends can't be estimated.")
        if dated and not self.repository.get_price_history():
            notes.append("Choose “Refresh prices” to download dividend history.")
        notes.append(
            "Estimates: shares held × each dividend per share, counted when you "
            "bought before the ex-dividend date (the date shown). Mutual fund "
            "capital gains distributions aren't included. Assumes no shares were "
            "sold. Select a row to edit it; a manual entry replaces the estimate "
            "for the same ticker and date, and $0 marks it as not received."
        )
        self.note.setText("\n".join(notes))

    def _selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            return
        entry = self.entries[rows.pop()]
        self.ticker_input.setText(entry.ticker)
        year, month, day = map(int, entry.date.split("-"))
        self.date_input.setDate(QDate(year, month, day))
        self.amount_input.setValue(round(entry.amount, 2))
        self.editing_manual_id = entry.manual_id
        is_manual = entry.source == MANUAL
        self.save_button.setText("Save changes" if is_manual else "Save as manual entry")
        self.delete_button.setEnabled(is_manual)
        self.cancel_button.setEnabled(True)

    def _save(self) -> None:
        try:
            self.repository.save_manual_dividend(
                self.portfolio_id,
                self.ticker_input.text(),
                self.date_input.date().toString("yyyy-MM-dd"),
                self.amount_input.value(),
                self.editing_manual_id,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Could not save dividend", str(error))
            return
        except sqlite3.Error as error:
            QMessageBox.critical(
                self, "Database error", f"The dividend could not be saved:\n{error}"
            )
            return
        self._reload_and_clear()

    def _delete(self) -> None:
        if self.editing_manual_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete dividend",
            "Delete this manual entry? If there's an estimate for the same "
            "ticker and date, it will show again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repository.delete_manual_dividend(
                self.editing_manual_id, self.portfolio_id
            )
        except LookupError as error:
            QMessageBox.warning(self, "Could not delete dividend", str(error))
        except sqlite3.Error as error:
            QMessageBox.critical(
                self, "Database error", f"The dividend could not be deleted:\n{error}"
            )
            return
        self._reload_and_clear()

    def _reload_and_clear(self) -> None:
        self._clear_form()
        self.reload(self.repository.list_holdings(self.portfolio_id))

    def _clear_form(self) -> None:
        self.table.clearSelection()
        self.editing_manual_id = None
        self.ticker_input.clear()
        self.date_input.setDate(QDate.currentDate())
        self.amount_input.setValue(0)
        self.save_button.setText("Add dividend")
        self.delete_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
