import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .cache import TTLCache
from .db import db_connection, db_execute, db_fetchone, init_db, is_duplicate_error, upsert_scan
from .gcs import blob_exists, download_blob_bytes, upload_path
from .qr import generate_qr_png
from .schemas import (
    AnalyticsResponse,
    CreateQrRequest,
    CreateQrResponse,
    ImageSpec,
    ScansByDay,
    UpdateQrRequest,
    UrlResponse,
)
from .settings import SETTINGS
from .storage import (
    build_cdn_url,
    image_object_name,
    image_path,
    normalize_spec,
    spec_hash,
    store_image,
)
from .tokens import generate_token


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


SETTINGS.storage_path.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="QR Code Generator", version="0.1.0", lifespan=lifespan)
cache = TTLCache(SETTINGS.cache_ttl_seconds)


app.mount("/static", StaticFiles(directory=SETTINGS.storage_path), name="static")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs", status_code=302)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(expires_at) -> bool:
    if expires_at is None:
        return False
    if isinstance(expires_at, str):
        return expires_at < now_iso()
    # datetime object returned by MySQL
    return expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)


def _expires_at_str(expires_at: Optional[datetime]) -> Optional[str]:
    return expires_at.isoformat() if expires_at else None


def get_active_record(conn, qr_token: str):
    return db_fetchone(
        conn,
        "SELECT * FROM qr_codes WHERE qr_token = ? AND status = 'active'",
        (qr_token,),
    )


def resolve_image_spec(
    dimension: Optional[int] = Query(None),
    color: Optional[str] = Query(None),
    border: Optional[int] = Query(None),
    image_spec: Optional[ImageSpec] = Body(default=None, embed=True),
) -> ImageSpec:
    if image_spec is not None:
        spec = image_spec
    else:
        try:
            spec = ImageSpec(
                dimension=(
                    dimension if dimension is not None else SETTINGS.default_dimension
                ),
                color=color if color is not None else SETTINGS.default_color,
                border=border if border is not None else SETTINGS.default_border,
            )
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

    if spec.dimension > SETTINGS.max_dimension:
        raise HTTPException(
            status_code=400,
            detail=f"dimension must be <= {SETTINGS.max_dimension}",
        )
    return spec


def record_scan(qr_token: str) -> None:
    scan_date = datetime.now(timezone.utc).date().isoformat()
    ts = now_iso()
    with db_connection() as conn:
        db_execute(
            conn,
            """
            UPDATE qr_codes
            SET scan_count = scan_count + 1, last_clicked_at = ?, updated_at = ?
            WHERE qr_token = ? AND status = 'active'
            """,
            (ts, ts, qr_token),
        )
        upsert_scan(conn, qr_token, scan_date)
        conn.commit()


@app.post("/api/qr/create", response_model=CreateQrResponse)
def create_qr_code(request: CreateQrRequest) -> CreateQrResponse:
    created_at = now_iso()
    expires_at = _expires_at_str(request.expires_at)
    with db_connection() as conn:
        for _ in range(10):
            qr_token = generate_token(
                request.url, SETTINGS.token_secret, SETTINGS.token_length
            )
            try:
                db_execute(
                    conn,
                    """
                    INSERT INTO qr_codes
                        (id, qr_token, url, status, created_at, updated_at, expires_at)
                    VALUES
                        (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), qr_token, request.url, created_at, created_at, expires_at),
                )
                conn.commit()
                cache.set(qr_token, {"url": request.url, "expires_at": expires_at})
                base = SETTINGS.public_base_url.rstrip("/")
                return CreateQrResponse(
                    token=qr_token,
                    short_url=f"{base}/r/{qr_token}",
                    qr_code_url=f"{base}/api/qr/{qr_token}/image",
                    original_url=request.url,
                )
            except Exception as exc:
                if is_duplicate_error(exc):
                    continue
                raise

    raise HTTPException(status_code=500, detail="Failed to generate unique token")


@app.get("/api/qr/{qr_token}/image", response_model=None)
def get_qr_code_image(
    qr_token: str,
    spec: ImageSpec = Depends(resolve_image_spec),
):
    with db_connection() as conn:
        record = get_active_record(conn, qr_token)
        if record is None:
            raise HTTPException(status_code=404, detail="QR code not found")

    spec_dict = normalize_spec(spec.dimension, spec.color, spec.border)
    hash_value = spec_hash(spec_dict)
    path = image_path(SETTINGS.storage_path, qr_token, hash_value)
    object_name = image_object_name(qr_token, hash_value)

    if path.exists():
        return FileResponse(path, media_type="image/png")

    if SETTINGS.gcp_bucket_name and blob_exists(SETTINGS.gcp_bucket_name, object_name):
        content = download_blob_bytes(SETTINGS.gcp_bucket_name, object_name)
        return Response(content=content, media_type="image/png")

    redirect_url = f"{SETTINGS.public_base_url.rstrip('/')}/r/{qr_token}"
    try:
        image = generate_qr_png(redirect_url, spec.dimension, spec.color, spec.border)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store_image(image, path)
    if SETTINGS.gcp_bucket_name:
        upload_path(SETTINGS.gcp_bucket_name, object_name, path)

    return FileResponse(path, media_type="image/png")


@app.get("/api/qr/{qr_token}", response_model=UrlResponse)
def get_qr_code(qr_token: str) -> UrlResponse:
    with db_connection() as conn:
        record = get_active_record(conn, qr_token)
        if record is None:
            raise HTTPException(status_code=404, detail="QR code not found")
        return UrlResponse(url=record["url"])


@app.patch("/api/qr/{qr_token}")
def update_qr_code(qr_token: str, request: UpdateQrRequest) -> Response:
    updated_at = now_iso()
    with db_connection() as conn:
        if request.expires_at is not None:
            cursor = db_execute(
                conn,
                """
                UPDATE qr_codes
                SET url = ?, updated_at = ?, expires_at = ?
                WHERE qr_token = ? AND status = 'active'
                """,
                (request.url, updated_at, _expires_at_str(request.expires_at), qr_token),
            )
        else:
            cursor = db_execute(
                conn,
                """
                UPDATE qr_codes
                SET url = ?, updated_at = ?
                WHERE qr_token = ? AND status = 'active'
                """,
                (request.url, updated_at, qr_token),
            )
        conn.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="QR code not found")

    # Invalidate cache; next redirect will repopulate from DB with correct expires_at
    cache.delete(qr_token)
    return Response(status_code=204)


@app.delete("/api/qr/{qr_token}")
def delete_qr_code(qr_token: str) -> Response:
    deleted_at = now_iso()
    with db_connection() as conn:
        cursor = db_execute(
            conn,
            """
            UPDATE qr_codes
            SET status = 'deleted', deleted_at = ?, updated_at = ?
            WHERE qr_token = ? AND status = 'active'
            """,
            (deleted_at, deleted_at, qr_token),
        )
        conn.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="QR code not found")

    cache.delete(qr_token)
    return Response(status_code=204)


@app.get("/api/qr/{qr_token}/analytics", response_model=AnalyticsResponse)
def get_analytics(qr_token: str) -> AnalyticsResponse:
    with db_connection() as conn:
        record = db_fetchone(
            conn,
            "SELECT scan_count FROM qr_codes WHERE qr_token = ? AND status = 'active'",
            (qr_token,),
        )
        if record is None:
            raise HTTPException(status_code=404, detail="QR code not found")

        scans_cursor = db_execute(
            conn,
            "SELECT scan_date, count FROM qr_scans WHERE qr_token = ? ORDER BY scan_date",
            (qr_token,),
        )
        scans_rows = scans_cursor.fetchall()

    scans_by_day = [ScansByDay(date=row["scan_date"], count=row["count"]) for row in scans_rows]
    return AnalyticsResponse(
        token=qr_token,
        total_scans=record["scan_count"],
        scans_by_day=scans_by_day,
    )


@app.get("/r/{qr_token}")
def redirect_to_url(qr_token: str, background_tasks: BackgroundTasks):
    cached = cache.get(qr_token)
    if cached is not None:
        if _is_expired(cached.get("expires_at")):
            cache.delete(qr_token)
            raise HTTPException(status_code=410, detail="QR code has expired")
        background_tasks.add_task(record_scan, qr_token)
        return RedirectResponse(url=cached["url"], status_code=302)

    with db_connection() as conn:
        record = db_fetchone(
            conn,
            "SELECT qr_token, url, status, expires_at FROM qr_codes WHERE qr_token = ?",
            (qr_token,),
        )

    if record is None:
        raise HTTPException(status_code=404, detail="QR code not found")
    if record["status"] == "deleted":
        raise HTTPException(status_code=410, detail="QR code has been deleted")
    if _is_expired(record["expires_at"]):
        raise HTTPException(status_code=410, detail="QR code has expired")

    ea = record["expires_at"]
    if isinstance(ea, datetime):
        ea = ea.isoformat()
    cache.set(qr_token, {"url": record["url"], "expires_at": ea})
    background_tasks.add_task(record_scan, qr_token)
    return RedirectResponse(url=record["url"], status_code=302)
