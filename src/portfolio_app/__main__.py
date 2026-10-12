"""Start the app with:  python -m portfolio_app"""
import sys

from PySide6.QtWidgets import QApplication

from portfolio_app.config import APP_NAME
from portfolio_app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
