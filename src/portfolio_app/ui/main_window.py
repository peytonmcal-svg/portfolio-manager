"""The main application window."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow

from portfolio_app.config import APP_NAME


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 650)

        placeholder = QLabel("Portfolio Manager is running. Holdings come next.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(placeholder)
