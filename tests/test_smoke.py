"""Basic check that the project is set up correctly."""
from portfolio_app import config


def test_data_folder_is_inside_project():
    assert config.DATA_DIR.parent == config.PROJECT_ROOT
    assert config.DB_PATH.suffix == ".db"
