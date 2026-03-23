import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .cache import TTLCache
from .db import db_connection, init_db
from .qr import generate_qr_png
from .schemas import (
    CreateQrRequest,
    CreateQrResponse,
    ImageSpec,
    UpdateQrRequest,
    UrlResponse,
)
from .settings import SETTINGS
from .storage import build_cdn_url, image_path, normalize_spec, spec_hash, store_image
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


def get_active_record(conn, qr_token: str):
    return conn.execute(
        "SELECT * FROM qr_codes WHERE qr_token = ? AND status = 'active'", (qr_token,)
    ).fetchone()


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
                dimension=dimension
                if dimension is not None
                else SETTINGS.default_dimension,
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


@app.post("/v1/qr_code", response_model=CreateQrResponse)
def create_qr_code(request: CreateQrRequest) -> CreateQrResponse:
    created_at = now_iso()
    with db_connection() as conn:
        for _ in range(10):
            qr_token = generate_token(
                request.url, SETTINGS.token_secret, SETTINGS.token_length
            )
            try:
                conn.execute(
                    """
                    INSERT INTO qr_codes
                        (id, qr_token, url, status, created_at, updated_at)
                    VALUES
                        (?, ?, ?, 'active', ?, ?)
                    """,
                    (str(uuid.uuid4()), qr_token, request.url, created_at, created_at),
                )
                conn.commit()
                cache.set(qr_token, request.url)
                return CreateQrResponse(qr_token=qr_token)
            except sqlite3.IntegrityError as exc:
                if "UNIQUE" in str(exc).upper():
                    continue
                raise

    raise HTTPException(status_code=500, detail="Failed to generate unique token")


@app.get("/v1/qr_code_image/{qr_token}")
def get_qr_code_image(
    qr_token: str, spec: ImageSpec = Depends(resolve_image_spec)
) -> dict:
    with db_connection() as conn:
        record = get_active_record(conn, qr_token)
        if record is None:
            raise HTTPException(status_code=404, detail="QR code not found")

    spec_dict = normalize_spec(spec.dimension, spec.color, spec.border)
    hash_value = spec_hash(spec_dict)
    path = image_path(SETTINGS.storage_path, qr_token, hash_value)

    if not path.exists():
        redirect_url = f"{SETTINGS.public_base_url.rstrip('/')}/{qr_token}"
        try:
            image = generate_qr_png(
                redirect_url, spec.dimension, spec.color, spec.border
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store_image(image, path)

    return {"image_location": build_cdn_url(SETTINGS.cdn_base_url, qr_token, hash_value)}


@app.get("/v1/qr_code/{qr_token}", response_model=UrlResponse)
def get_qr_code(qr_token: str) -> UrlResponse:
    with db_connection() as conn:
        record = get_active_record(conn, qr_token)
        if record is None:
            raise HTTPException(status_code=404, detail="QR code not found")
        return UrlResponse(url=record["url"])


@app.put("/v1/qr_code/{qr_token}")
def update_qr_code(qr_token: str, request: UpdateQrRequest) -> Response:
    updated_at = now_iso()
    with db_connection() as conn:
        cursor = conn.execute(
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

    cache.set(qr_token, request.url)
    return Response(status_code=204)


@app.delete("/v1/qr_code/{qr_token}")
def delete_qr_code(qr_token: str) -> Response:
    deleted_at = now_iso()
    with db_connection() as conn:
        cursor = conn.execute(
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


@app.get("/{qr_token}")
def redirect_to_url(qr_token: str):
    url = cache.get(qr_token)
    updated_at = now_iso()

    with db_connection() as conn:
        if url is None:
            record = get_active_record(conn, qr_token)
            if record is None:
                raise HTTPException(status_code=404, detail="QR code not found")
            url = record["url"]
            cache.set(qr_token, url)

        cursor = conn.execute(
            """
            UPDATE qr_codes
            SET last_clicked_at = ?, updated_at = ?
            WHERE qr_token = ? AND status = 'active'
            """,
            (updated_at, updated_at, qr_token),
        )
        conn.commit()

    if cursor.rowcount == 0:
        cache.delete(qr_token)
        raise HTTPException(status_code=404, detail="QR code not found")

    return RedirectResponse(url=url, status_code=302)
