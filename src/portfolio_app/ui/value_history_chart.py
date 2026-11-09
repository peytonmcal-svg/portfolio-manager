"""A line chart of daily portfolio value against money invested."""
from datetime import date

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PySide6.QtGui import QCursor, QPalette
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from portfolio_app.services.history import ValuePoint

LIGHT_COLORS = {
    "value": "#2a78d6", "invested": "#52514e",
    "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df",
}
DARK_COLORS = {
    "value": "#3987e5", "invested": "#c3c2b7",
    "text": "#f0efec", "muted": "#c3c2b7", "grid": "#383835",
}


class ValueHistoryChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.points: list[ValuePoint] = []
        self.dates: list[date] = []
        self.axes = None
        self.crosshair = None
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("motion_notify_event", self._show_tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def set_points(self, points: list[ValuePoint], empty_message: str) -> None:
        self.points = points
        self.dates = [date.fromisoformat(point.date) for point in points]
        background = self.palette().color(QPalette.ColorRole.Window)
        colors = DARK_COLORS if background.lightness() < 128 else LIGHT_COLORS
        self.figure.clear()
        self.figure.set_facecolor(background.name())
        axes = self.figure.add_subplot()
        self.axes = axes
        axes.set_facecolor(background.name())
        axes.set_title(
            "Portfolio value", loc="left", color=colors["text"], fontsize=12
        )

        if not points:
            self.crosshair = None
            axes.set_axis_off()
            axes.text(
                0.5, 0.5, empty_message,
                ha="center", va="center",
                color=colors["muted"], transform=axes.transAxes,
            )
            self.canvas.draw_idle()
            return

        values = [point.market_value for point in points]
        axes.plot(
            self.dates, [point.invested for point in points],
            color=colors["invested"], linewidth=1.5, linestyle="--",
            label="Money invested",
        )
        axes.plot(
            self.dates, values,
            color=colors["value"], linewidth=2, label="Portfolio value",
        )
        axes.annotate(
            f"${values[-1]:,.0f}",
            xy=(self.dates[-1], values[-1]),
            xytext=(6, 0), textcoords="offset points",
            va="center", color=colors["text"], fontsize=9,
        )

        locator = AutoDateLocator()
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axes.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _: f"${value:,.0f}")
        )
        axes.grid(axis="y", color=colors["grid"], linewidth=0.8)
        axes.set_axisbelow(True)
        for side in ("top", "right", "left"):
            axes.spines[side].set_visible(False)
        axes.spines["bottom"].set_color(colors["muted"])
        axes.tick_params(colors=colors["muted"], labelsize=9, length=0)
        legend = axes.legend(loc="upper left", frameon=False, fontsize=9)
        for text in legend.get_texts():
            text.set_color(colors["text"])
        self.crosshair = axes.axvline(
            self.dates[0], color=colors["muted"], linewidth=0.8, visible=False
        )
        self.canvas.draw_idle()

    def _show_tooltip(self, event) -> None:
        if self.crosshair is None or event.inaxes is not self.axes:
            if self.crosshair is not None and self.crosshair.get_visible():
                self.crosshair.set_visible(False)
                self.canvas.draw_idle()
            QToolTip.hideText()
            return

        # Snap to the nearest trading day.
        numeric_dates = date2num(self.dates)
        index = min(
            range(len(self.dates)),
            key=lambda i: abs(numeric_dates[i] - event.xdata),
        )
        point = self.points[index]
        self.crosshair.set_xdata([self.dates[index]])
        self.crosshair.set_visible(True)
        self.canvas.draw_idle()
        gain = point.market_value - point.invested
        sign = "+" if gain >= 0 else "-"
        QToolTip.showText(
            QCursor.pos(),
            f"{point.date}\n"
            f"Value: ${point.market_value:,.2f}\n"
            f"Invested: ${point.invested:,.2f}\n"
            f"Gain/loss: {sign}${abs(gain):,.2f}",
        )
