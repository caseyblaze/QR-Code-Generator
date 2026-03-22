# Copilot Instructions

Project: QR-Code-Generator

## Build, test, lint
- Install deps: `pip install -r requirements.txt`
- Run server: `uvicorn app.main:app --reload`
- Run tests: `python3 -m pytest`
- No lint command is defined yet.

## High-level architecture
- FastAPI app lives in `app/main.py` with REST endpoints under `/v1` and a root redirect `/{qr_token}`.
- SQLite stores QR metadata in `data/qr_codes.db` (schema and init in `app/db.py`).
- QR images are generated with `qrcode`/Pillow and stored under `storage/qr/{qr_token}/{spec_hash}.png`.
- Static files are served via `app.mount("/static", ...)`, and image URLs use `CDN_BASE_URL`.
- Cleanup is handled by `scripts/cleanup.py`, which marks inactive QR codes as deleted.

## Key conventions
- Input URLs must be ASCII and <= 20 characters.
- Tokens are 10-char Base62 derived from SHA-256(url + nonce + secret); collisions retry on UNIQUE constraint.
- Image specs are normalized and hashed; identical specs reuse the same stored image.
- Environment configuration is centralized in `app/settings.py`.
