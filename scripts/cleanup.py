from datetime import datetime, timedelta, timezone

from app.db import db_connection, db_execute, init_db
from app.settings import SETTINGS


def main() -> None:
    init_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=SETTINGS.retention_days)
    cutoff_iso = cutoff.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    with db_connection() as conn:
        cursor = db_execute(
            conn,
            """
            UPDATE qr_codes
            SET status = 'deleted', deleted_at = ?, updated_at = ?
            WHERE status = 'active'
            AND COALESCE(last_clicked_at, created_at) < ?
            """,
            (now_iso, now_iso, cutoff_iso),
        )
        conn.commit()

    print(f"Marked {cursor.rowcount} QR codes as deleted.")


if __name__ == "__main__":
    main()
