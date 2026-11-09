"""A line chart of daily portfolio value, money invested, and the SPY comparison."""
from datetime import date

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PySide6.QtGui import QCursor, QPalette
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from portfolio_app.services.history import BENCHMARK_TICKER, BenchmarkPoint, ValuePoint

LIGHT_COLORS = {
    "value": "#2a78d6", "benchmark": "#eb6834", "invested": "#52514e",
    "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df",
}
DARK_COLORS = {
    "value": "#3987e5", "benchmark": "#d95926", "invested": "#c3c2b7",
    "text": "#f0efec", "muted": "#c3c2b7", "grid": "#383835",
}
BENCHMARK_LABEL = f"If invested in {BENCHMARK_TICKER}"


class ValueHistoryChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.points: list[ValuePoint] = []
        self.benchmark_by_date: dict[str, BenchmarkPoint] = {}
        self.dates: list[date] = []
        self.axes = None
        self.crosshair = None
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("motion_notify_event", self._show_tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def set_points(
        self,
        points: list[ValuePoint],
        benchmark_points: list[BenchmarkPoint],
        empty_message: str,
    ) -> None:
        self.points = points
        self.benchmark_by_date = {point.date: point for point in benchmark_points}
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
        end_labels = [(self.dates[-1], values[-1], colors["value"])]
        # Only draw the benchmark over the portfolio's date range.
        benchmark_points = [
            point for point in benchmark_points
            if self.points[0].date <= point.date <= self.points[-1].date
        ]
        if benchmark_points:
            benchmark_dates = [date.fromisoformat(p.date) for p in benchmark_points]
            benchmark_values = [point.value for point in benchmark_points]
            axes.plot(
                benchmark_dates, benchmark_values,
                color=colors["benchmark"], linewidth=2, label=BENCHMARK_LABEL,
            )
            end_labels.append(
                (benchmark_dates[-1], benchmark_values[-1], colors["benchmark"])
            )
        axes.plot(
            self.dates, values,
            color=colors["value"], linewidth=2, label="Portfolio value",
        )
        self._label_line_ends(axes, end_labels, colors["text"])

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
        # Lines are drawn bottom-to-top; list them in the legend top-to-bottom.
        handles, labels = axes.get_legend_handles_labels()
        legend = axes.legend(
            handles[::-1], labels[::-1],
            loc="upper left", frameon=False, fontsize=9,
        )
        for text in legend.get_texts():
            text.set_color(colors["text"])
        self.crosshair = axes.axvline(
            self.dates[0], color=colors["muted"], linewidth=0.8, visible=False
        )
        self.canvas.draw_idle()

    @staticmethod
    def _label_line_ends(axes, end_labels, text_color) -> None:
        """Write each line's latest value at its right end, kept apart if close."""
        low, high = axes.get_ylim()
        too_close = (high - low) * 0.04
        ordered = sorted(end_labels, key=lambda label: label[1])
        offsets = [0.0] * len(ordered)
        if len(ordered) == 2 and ordered[1][1] - ordered[0][1] < too_close:
            offsets = [-6.0, 6.0]
        for (x, y, line_color), offset in zip(ordered, offsets):
            axes.plot([x], [y], marker="o", markersize=4, color=line_color)
            axes.annotate(
                f"${y:,.0f}",
                xy=(x, y), xytext=(8, offset), textcoords="offset points",
                va="center", color=text_color, fontsize=9,
            )

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
        lines = [
            point.date,
            f"Portfolio value: ${point.market_value:,.2f}",
        ]
        benchmark = self.benchmark_by_date.get(point.date)
        if benchmark is not None:
            lines.append(f"{BENCHMARK_LABEL}: ${benchmark.value:,.2f}")
        lines.append(f"Money invested: ${point.invested:,.2f}")
        QToolTip.showText(QCursor.pos(), "\n".join(lines))
