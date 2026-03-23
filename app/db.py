import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .settings import SETTINGS


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    _ensure_parent(SETTINGS.db_path)
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qr_codes (
                id TEXT PRIMARY KEY,
                qr_token TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_clicked_at TEXT,
                deleted_at TEXT
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_qr_codes_token ON qr_codes(qr_token);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_qr_codes_last_clicked ON qr_codes(last_clicked_at);"
        )
        conn.commit()


@contextmanager
def db_connection():
    conn = sqlite3.connect(str(SETTINGS.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
