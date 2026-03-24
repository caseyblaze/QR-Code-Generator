import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

try:
    import pymysql
    import pymysql.cursors
except ImportError:  # pragma: no cover - optional dependency
    pymysql = None

from .settings import SETTINGS


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _using_mysql() -> bool:
    return SETTINGS.database_url is not None


def _parse_mysql_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("DATABASE_URL must use mysql or mysql+pymysql scheme")

    db_name = parsed.path.lstrip("/")
    if not db_name:
        raise ValueError("DATABASE_URL must include a database name")

    query = parse_qs(parsed.query)
    unix_socket = query.get("unix_socket", [None])[0]

    return {
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "database": db_name,
        "unix_socket": unix_socket,
    }


def _init_sqlite() -> None:
    _ensure_parent(SETTINGS.db_path)
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_qr_codes_token ON qr_codes(qr_token);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_qr_codes_last_clicked ON qr_codes(last_clicked_at);"
        )
        conn.commit()


def _init_mysql() -> None:
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS qr_codes (
                id VARCHAR(64) PRIMARY KEY,
                qr_token VARCHAR(32) NOT NULL UNIQUE,
                url TEXT NOT NULL,
                status VARCHAR(16) NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_clicked_at TEXT,
                deleted_at TEXT
            ) CHARACTER SET utf8mb4;
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_qr_codes_token ON qr_codes(qr_token);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_qr_codes_last_clicked ON qr_codes(last_clicked_at);"
        )
        conn.commit()


def init_db() -> None:
    if _using_mysql():
        _init_mysql()
    else:
        _init_sqlite()


def _adapt_query(query: str) -> str:
    if _using_mysql():
        return query.replace("?", "%s")
    return query


def db_execute(conn, query: str, params: Optional[tuple] = None):
    cursor = conn.cursor()
    if params is None:
        cursor.execute(_adapt_query(query))
    else:
        cursor.execute(_adapt_query(query), params)
    return cursor


def db_fetchone(conn, query: str, params: Optional[tuple] = None):
    cursor = db_execute(conn, query, params)
    return cursor.fetchone()


def is_duplicate_error(exc: Exception) -> bool:
    if _using_mysql() and pymysql is not None:
        if isinstance(exc, pymysql.err.IntegrityError):
            return bool(exc.args) and exc.args[0] == 1062
    if isinstance(exc, sqlite3.IntegrityError):
        return "UNIQUE" in str(exc).upper()
    return False


@contextmanager
def db_connection():
    if _using_mysql():
        if pymysql is None:
            raise RuntimeError("PyMySQL is required when DATABASE_URL is set")
        config = _parse_mysql_url(SETTINGS.database_url)
        conn = pymysql.connect(
            user=config["user"],
            password=config["password"],
            host=config["host"],
            port=config["port"],
            database=config["database"],
            unix_socket=config["unix_socket"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            charset="utf8mb4",
        )
    else:
        conn = sqlite3.connect(str(SETTINGS.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
