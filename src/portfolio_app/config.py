"""App-wide settings and file locations."""
from pathlib import Path

APP_NAME = "Portfolio Manager"

# Project root = three folders up from this file (src/portfolio_app/config.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "portfolio.db"
