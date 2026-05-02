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
                deleted_at TEXT,
                expires_at TEXT,
                scan_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS qr_scans (
                qr_token TEXT NOT NULL,
                scan_date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (qr_token, scan_date)
            );
            """
        )
        # Migration: add new columns to existing databases
        for ddl in (
            "ALTER TABLE qr_codes ADD COLUMN expires_at TEXT",
            "ALTER TABLE qr_codes ADD COLUMN scan_count INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                cursor.execute(ddl)
            except sqlite3.OperationalError:
                pass  # Column already exists
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
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                last_clicked_at TIMESTAMP,
                deleted_at TIMESTAMP,
                expires_at TIMESTAMP NULL,
                scan_count INT NOT NULL DEFAULT 0
            ) CHARACTER SET utf8mb4;
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS qr_scans (
                qr_token VARCHAR(32) NOT NULL,
                scan_date DATE NOT NULL,
                count INT NOT NULL DEFAULT 0,
                PRIMARY KEY (qr_token, scan_date)
            ) CHARACTER SET utf8mb4;
            """
        )
        # Migration: add new columns to existing databases
        for ddl in (
            "ALTER TABLE qr_codes ADD COLUMN expires_at TIMESTAMP NULL",
            "ALTER TABLE qr_codes ADD COLUMN scan_count INT NOT NULL DEFAULT 0",
        ):
            try:
                cursor.execute(ddl)
            except pymysql.err.OperationalError as exc:
                if bool(exc.args) and exc.args[0] == 1060:  # Duplicate column name
                    pass
                else:
                    raise
        _ensure_mysql_index(cursor, "qr_codes", "idx_qr_codes_token", "qr_token")
        _ensure_mysql_index(
            cursor, "qr_codes", "idx_qr_codes_last_clicked", "last_clicked_at"
        )
        conn.commit()


def init_db() -> None:
    if _using_mysql():
        _init_mysql()
    else:
        _init_sqlite()


def _mysql_index_exists(cursor, table: str, index: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(1) AS count
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table, index),
    )
    row = cursor.fetchone()
    return bool(row and row["count"] > 0)


def _ensure_mysql_index(cursor, table: str, index: str, column: str) -> None:
    if _mysql_index_exists(cursor, table, index):
        return
    try:
        cursor.execute(f"CREATE INDEX {index} ON {table}({column});")
    except pymysql.err.OperationalError as exc:
        if bool(exc.args) and exc.args[0] == 1061:
            return
        raise


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


def upsert_scan(conn, qr_token: str, scan_date: str) -> None:
    if _using_mysql():
        db_execute(
            conn,
            "INSERT INTO qr_scans (qr_token, scan_date, count) VALUES (?, ?, 1)"
            " ON DUPLICATE KEY UPDATE count = count + 1",
            (qr_token, scan_date),
        )
    else:
        db_execute(
            conn,
            "INSERT INTO qr_scans (qr_token, scan_date, count) VALUES (?, ?, 1)"
            " ON CONFLICT (qr_token, scan_date) DO UPDATE SET count = count + 1",
            (qr_token, scan_date),
        )


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
