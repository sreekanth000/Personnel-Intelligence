import os

DEFAULT_DB_PATH = os.path.expanduser("~/.personal_intelligence/pi_data.db")
DEFAULT_LOG_PATH = os.path.expanduser("~/.personal_intelligence/logs/")


def get_db_path() -> str:
    """Returns the configured or default database path."""
    return os.environ.get("PI_DB_PATH", DEFAULT_DB_PATH)
