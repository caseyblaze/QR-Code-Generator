# QR-Code-Generator

A simple QR Code Generator service built with FastAPI.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Testing

```bash
python3 -m pytest
```

## Environment

- `DB_PATH` (default: `data/qr_codes.db`)
- `STORAGE_PATH` (default: `storage`)
- `CDN_BASE_URL` (default: `http://localhost:8000/static`)
- `PUBLIC_BASE_URL` (default: `http://localhost:8000`)
- `TOKEN_SECRET` (default: `dev-secret`)
- `RETENTION_DAYS` (default: `7`)
- `CACHE_TTL_SECONDS` (default: `300`)
- `DEFAULT_DIMENSION` (default: `256`)
- `DEFAULT_COLOR` (default: `#000000`)
- `DEFAULT_BORDER` (default: `4`)
- `MAX_DIMENSION` (default: `1024`)

## API

Create a QR code:

```bash
curl -X POST http://localhost:8000/v1/qr_code \
  -H "Content-Type: application/json" \
  -d '{"url":"https://ex.com"}'
```

Get QR code image (query params) or via body `{ "image_spec": { ... } }`:

```bash
curl "http://localhost:8000/v1/qr_code_image/ABC123?dimension=256&color=%23000000&border=4"
```

Get or manage a QR code:

```bash
curl http://localhost:8000/v1/qr_code/ABC123
curl -X PUT http://localhost:8000/v1/qr_code/ABC123 -H "Content-Type: application/json" -d '{"url":"https://ex.com"}'
curl -X DELETE http://localhost:8000/v1/qr_code/ABC123
```

Redirect:

```bash
curl -I http://localhost:8000/ABC123
```

## Cleanup job

```bash
python3 scripts/cleanup.py
```
