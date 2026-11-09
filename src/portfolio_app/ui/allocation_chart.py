"""A horizontal bar chart showing each group's share of portfolio value."""
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtGui import QCursor, QPalette
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from portfolio_app.services.allocation import AllocationSlice

LIGHT_COLORS = {"bar": "#2a78d6", "text": "#0b0b0b", "muted": "#52514e"}
DARK_COLORS = {"bar": "#3987e5", "text": "#f0efec", "muted": "#c3c2b7"}


class AllocationChart(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.slices: list[AllocationSlice] = []
        self.bars = None
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("motion_notify_event", self._show_tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def set_slices(self, slices: list[AllocationSlice], empty_message: str) -> None:
        self.slices = slices
        background = self.palette().color(QPalette.ColorRole.Window)
        colors = DARK_COLORS if background.lightness() < 128 else LIGHT_COLORS
        self.figure.clear()
        self.figure.set_facecolor(background.name())
        axes = self.figure.add_subplot()
        axes.set_facecolor(background.name())
        axes.set_title(self.title, loc="left", color=colors["text"], fontsize=12)

        if not slices:
            self.bars = None
            axes.set_axis_off()
            axes.text(
                0.5, 0.5, empty_message,
                ha="center", va="center", wrap=True,
                color=colors["muted"], transform=axes.transAxes,
            )
            self.canvas.draw_idle()
            return

        labels = [item.label for item in slices]
        percents = [item.percent for item in slices]
        self.bars = axes.barh(labels, percents, height=0.6, color=colors["bar"])
        axes.invert_yaxis()
        axes.bar_label(
            self.bars,
            labels=[f"{value:.1f}%" for value in percents],
            padding=4,
            color=colors["text"],
            fontsize=9,
        )
        axes.set_xlim(0, max(percents) * 1.15)
        axes.xaxis.set_visible(False)
        for side in ("top", "right", "bottom"):
            axes.spines[side].set_visible(False)
        axes.spines["left"].set_color(colors["muted"])
        axes.tick_params(axis="y", colors=colors["text"], length=0, labelsize=9)
        self.canvas.draw_idle()

    def _show_tooltip(self, event) -> None:
        # Hovering anywhere in a bar's row counts, so thin bars are easy to hit.
        if self.bars is not None and event.inaxes is not None:
            row = round(event.ydata)
            if 0 <= row < len(self.slices):
                item = self.slices[row]
                QToolTip.showText(
                    QCursor.pos(),
                    f"{item.label}: ${item.market_value:,.2f} ({item.percent:.1f}%)",
                )
                return
        QToolTip.hideText()
