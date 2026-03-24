# QR-Code-Generator

A simple QR Code Generator service built with FastAPI.

## Architecture

![Architecture Diagram](docs/architecture.png)

## Interaction Flow

![Interaction Flow Diagram](docs/flow.png)

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

- `DATABASE_URL` (optional; when set uses MySQL instead of SQLite)
  - Cloud SQL unix socket example:
    `mysql+pymysql://USER:PASSWORD@/DB_NAME?unix_socket=/cloudsql/PROJECT:REGION:INSTANCE`
  - TCP example:
    `mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/DB_NAME`
- `DB_PATH` (default: `data/qr_codes.db`)
- `STORAGE_PATH` (default: `storage`)
- `GCP_BUCKET_NAME` (optional; when set, uploads QR images to this bucket)
- `CDN_BASE_URL` (default: `http://localhost:8000/static`)
  Note: If `GCP_BUCKET_NAME` is set and `CDN_BASE_URL` is not, it defaults to
  `https://storage.googleapis.com/<bucket>`. In Cloud Run or production, set this
  to a publicly accessible image base URL (for example, `https://YOUR_SERVICE_URL/static`
  or a CDN/GCS public URL). Otherwise `v1/qr_code_image/{qr_token}` may return
  `localhost` links.
- `PUBLIC_BASE_URL` (default: `http://localhost:8000`)
- `TOKEN_SECRET` (default: `dev-secret`)
- `RETENTION_DAYS` (default: `7`)
- `CACHE_TTL_SECONDS` (default: `300`)
- `DEFAULT_DIMENSION` (default: `256`)
- `DEFAULT_COLOR` (default: `#000000`)
- `DEFAULT_BORDER` (default: `4`)
- `MAX_DIMENSION` (default: `1024`)

## Deploy to GCP (Cloud Run + Cloud Storage)

This repository uses SQLite and local disk storage by default. For Cloud Run, use a
managed database for metadata (for example Firestore) and Cloud Storage for images.
When `GCP_BUCKET_NAME` is set, images are uploaded to the bucket and `image_location`
returns the CDN/GCS URL.

- `GCP_PROJECT_ID` (used for GCS client project selection if provided)
- `GCP_BUCKET_NAME`
- `GOOGLE_APPLICATION_CREDENTIALS` (optional locally; use Workload Identity on Cloud Run)
- `CDN_BASE_URL` (use the GCS public URL or a CDN in front of the bucket)
- `PUBLIC_BASE_URL` (your Cloud Run service URL)

Minimal Cloud Run deploy flow:

```bash
gcloud init
gcloud config set project YOUR_PROJECT_ID

gcloud services enable run.googleapis.com storage.googleapis.com firestore.googleapis.com

gsutil mb -l asia-east1 gs://YOUR_BUCKET_NAME

gcloud run deploy qr-generator \
  --source . \
  --platform managed \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=YOUR_PROJECT_ID,GCP_BUCKET_NAME=YOUR_BUCKET_NAME"
```

If you want public image URLs, make the bucket or a prefix public. For private
images, use signed URLs.

## API

Create a QR code:

```bash
curl -X POST http://localhost:8000/v1/qr_code \
  -H "Content-Type: application/json" \
  -d '{"url":"https://ex.com"}'
```

Get QR code image (query params) or via body `{ "image_spec": { ... } }`.
Add `raw=true` to return the PNG directly:

```bash
curl "http://localhost:8000/v1/qr_code_image/ABC123?dimension=256&color=%23000000&border=4"
curl "http://localhost:8000/v1/qr_code_image/ABC123?dimension=256&color=%23000000&border=4&raw=true"
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
