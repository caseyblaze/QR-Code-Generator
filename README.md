# QR Code Generator

A FastAPI service that generates short URLs backed by QR codes, with scan analytics, configurable image rendering, and optional Google Cloud Storage integration.

---

## System Architecture

```mermaid
flowchart TB
    Client["Client / Browser"]

    subgraph App["FastAPI Application (app/main.py)"]
        direction TB
        API["Route Handlers"]
        Cache["TTL Cache\n(app/cache.py)"]
        TokenGen["Token Generator\n(app/tokens.py)"]
        QRGen["QR Generator\n(app/qr.py)"]
        Validator["URL Validator\n(app/schemas.py)"]
    end

    subgraph Storage["Image Storage"]
        LocalDisk["Local Disk\nstorage/qr/{token}/{hash}.png"]
        GCS["Google Cloud Storage\n(app/gcs.py)"]
    end

    subgraph DB["Database (app/db.py)"]
        SQLite["SQLite\n(default)"]
        MySQL["MySQL / Cloud SQL\n(optional)"]
    end

    Client -->|"POST /api/qr/create\nGET /api/qr/{token}\nPATCH /api/qr/{token}\nDELETE /api/qr/{token}\nGET /r/{token}"| API
    API --> Cache
    API --> TokenGen
    API --> QRGen
    API --> Validator
    API --> DB
    QRGen --> LocalDisk
    LocalDisk -->|"GCP_BUCKET_NAME set"| GCS
    DB --- SQLite
    DB --- MySQL
    App -->|"GET /static/*"| LocalDisk
```

---

## Components

| Component | File | Responsibility |
|-----------|------|----------------|
| API Layer | `app/main.py` | Route handlers, request lifecycle |
| Database | `app/db.py` | SQLite / MySQL abstraction, connection management |
| Cache | `app/cache.py` | Thread-safe TTL in-memory cache for redirect hot path |
| QR Generator | `app/qr.py` | PIL/qrcode PNG rendering |
| Storage | `app/storage.py` | Image path resolution, spec hashing, local/GCS writes |
| GCS Client | `app/gcs.py` | Blob existence check, download, upload |
| Token | `app/tokens.py` | SHA-256 + base62 token generation with collision retry |
| Schemas | `app/schemas.py` | Pydantic request/response models and URL validation |
| Settings | `app/settings.py` | Environment-variable config (frozen dataclass) |
| Cleanup | `scripts/cleanup.py` | Retention-based soft-delete sweep |

---

## Data Model

```mermaid
erDiagram
    qr_codes {
        TEXT id PK
        TEXT qr_token UK
        TEXT url
        TEXT status
        TEXT created_at
        TEXT updated_at
        TEXT last_clicked_at
        TEXT deleted_at
        TEXT expires_at
        INTEGER scan_count
    }

    qr_scans {
        TEXT qr_token PK
        TEXT scan_date PK
        INTEGER count
    }

    qr_codes ||--o{ qr_scans : "token"
```

- `qr_codes.status` values: `active`, `deleted`
- Soft-delete: `DELETE` sets `status = 'deleted'`; rows are retained for analytics
- `qr_scans` uses an upsert keyed on `(qr_token, scan_date)` to aggregate daily counts

---

## API Endpoints

| Method | Path | Status Codes | Description |
|--------|------|--------------|-------------|
| `POST` | `/api/qr/create` | 200, 422, 500 | Create a QR code; returns token, short URL, image URL |
| `GET` | `/api/qr/{token}` | 200, 404 | Retrieve original URL metadata |
| `PATCH` | `/api/qr/{token}` | 204, 404 | Update target URL and/or expiration |
| `DELETE` | `/api/qr/{token}` | 204, 404 | Soft-delete (invalidates cache) |
| `GET` | `/api/qr/{token}/image` | 200, 404, 422 | Serve QR PNG; accepts `dimension`, `color`, `border` params |
| `GET` | `/api/qr/{token}/analytics` | 200, 404 | Return `total_scans` and `scans_by_day` |
| `GET` | `/r/{token}` | 302, 404, 410 | Redirect to target URL; records scan asynchronously |

### Request / Response Shapes

**Create QR code**
```json
POST /api/qr/create
{ "url": "https://example.com", "expires_at": "2025-12-31T00:00:00Z" }

200 → { "token": "aB3xZ9qRtY", "short_url": "…/r/aB3xZ9qRtY",
         "qr_code_url": "…/api/qr/aB3xZ9qRtY/image", "original_url": "…" }
```

**Get QR image**
```
GET /api/qr/{token}/image?dimension=512&color=%23ff0000&border=4
→ image/png
```

**Analytics**
```json
GET /api/qr/{token}/analytics
200 → { "token": "…", "total_scans": 42,
         "scans_by_day": [{ "date": "2025-01-15", "count": 7 }, …] }
```

---

## Key Flows

### QR Code Creation

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant V as URL Validator
    participant T as Token Generator
    participant DB as Database
    participant CH as TTL Cache

    C->>API: POST /api/qr/create {url, expires_at?}
    API->>V: validate url (ASCII, scheme, private-IP check)
    V-->>API: normalized url
    loop up to 10 retries (collision avoidance)
        API->>T: generate_token(url, secret, length)
        T-->>API: base62 token (SHA-256)
        API->>DB: INSERT qr_codes (UNIQUE qr_token)
        alt duplicate token
            DB-->>API: IntegrityError → retry
        else success
            DB-->>API: ok
        end
    end
    API->>CH: cache.set(token, {url, expires_at})
    API-->>C: 200 {token, short_url, qr_code_url, original_url}
```

### Short URL Redirect

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant CH as TTL Cache
    participant DB as Database
    participant BG as Background Task

    C->>API: GET /r/{token}
    API->>CH: cache.get(token)
    alt cache hit
        CH-->>API: {url, expires_at}
        alt expired
            API-->>C: 410 Gone
        else valid
            API->>BG: record_scan(token) [async]
            API-->>C: 302 → url
        end
    else cache miss
        API->>DB: SELECT qr_codes WHERE token = ?
        alt not found
            DB-->>API: None
            API-->>C: 404 Not Found
        else deleted
            DB-->>API: status = deleted
            API-->>C: 410 Gone
        else expired
            DB-->>API: expires_at < now
            API-->>C: 410 Gone
        else active
            DB-->>API: row
            API->>CH: cache.set(token, {url, expires_at})
            API->>BG: record_scan(token) [async]
            API-->>C: 302 → url
        end
    end
```

### QR Image Serving

```mermaid
flowchart LR
    A["GET /api/qr/{token}/image\n?dimension&color&border"] --> B{token active\nin DB?}
    B -->|no| E1["404 Not Found"]
    B -->|yes| C{local file\nexists?}
    C -->|yes| F1["FileResponse (disk)"]
    C -->|no| D{GCS bucket\nconfigured?}
    D -->|yes| G{blob exists\nin GCS?}
    G -->|yes| F2["Response (GCS bytes)"]
    G -->|no| H["generate_qr_png()\n(PIL + qrcode)"]
    D -->|no| H
    H --> I["store_image() → local disk"]
    I --> J{GCS bucket\nconfigured?}
    J -->|yes| K["upload_path() → GCS"]
    J -->|no| L["FileResponse (disk)"]
    K --> L
```

---

## Storage Strategy

Image filenames are derived from a hash of the rendering spec (`dimension`, `color`, `border`) so each unique visual variant is cached exactly once.

```
storage/qr/{qr_token}/{spec_hash}.png          ← local disk
gs://{GCP_BUCKET_NAME}/qr/{qr_token}/{hash}.png ← GCS (when configured)
```

**CDN base URL resolution:**

| `GCP_BUCKET_NAME` | `CDN_BASE_URL` set? | Effective base URL |
|-------------------|--------------------|--------------------|
| not set | — | `http://localhost:8000/static` |
| set | no | `https://storage.googleapis.com/{bucket}` |
| set | yes | value of `CDN_BASE_URL` |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | _(unset)_ | MySQL connection string; omit to use SQLite |
| `DB_PATH` | `data/qr_codes.db` | SQLite file location |
| `STORAGE_PATH` | `storage` | Local image storage root |
| `GCP_PROJECT_ID` | _(unset)_ | GCP project (used for GCS client) |
| `GCP_BUCKET_NAME` | _(unset)_ | GCS bucket; enables cloud image storage |
| `CDN_BASE_URL` | _(derived)_ | Public base URL for image links |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Base URL for short links and QR redirect targets |
| `TOKEN_SECRET` | `dev-secret` | Seed for SHA-256 token hashing |
| `TOKEN_LENGTH` | `10` | Base62 token length |
| `RETENTION_DAYS` | `7` | Days of inactivity before cleanup job deletes a code |
| `CACHE_TTL_SECONDS` | `300` | Redirect cache TTL |
| `DEFAULT_DIMENSION` | `256` | Default QR image size (px) |
| `DEFAULT_COLOR` | `#000000` | Default QR foreground color |
| `DEFAULT_BORDER` | `4` | Default QR border width |
| `MAX_DIMENSION` | `1024` | Maximum allowed image dimension (px) |

**MySQL connection string formats:**

```
# TCP
mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/DB_NAME

# Cloud SQL unix socket (Cloud Run)
mysql+pymysql://USER:PASSWORD@/DB_NAME?unix_socket=/cloudsql/PROJECT:REGION:INSTANCE
```

---

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive API docs available at `http://localhost:8000/docs`.

### Testing

```bash
python3 -m pytest
```

---

## Deploy to GCP (Cloud Run + Cloud Storage)

```mermaid
flowchart LR
    A["gcloud init\n+ set project"] --> B["Enable APIs\nrun / storage / sql"]
    B --> C["gsutil mb\nCreate GCS bucket"]
    C --> D["gcloud run deploy\n--source .\n--set-env-vars GCP_BUCKET_NAME=…"]
    D --> E["Cloud Run service\n(stateless, auto-scaled)"]
    E -->|images| F["Cloud Storage bucket"]
    E -->|metadata| G["Cloud SQL / MySQL\n(via unix socket)"]
```

```bash
gcloud init
gcloud config set project YOUR_PROJECT_ID

gcloud services enable run.googleapis.com storage.googleapis.com

gsutil mb -l asia-east1 gs://YOUR_BUCKET_NAME

gcloud run deploy qr-generator \
  --source . \
  --platform managed \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=YOUR_PROJECT_ID,GCP_BUCKET_NAME=YOUR_BUCKET_NAME,PUBLIC_BASE_URL=https://YOUR_SERVICE_URL"
```

On Cloud Run, authentication to GCS uses Workload Identity — no `GOOGLE_APPLICATION_CREDENTIALS` needed.

---

## Cleanup Job

Soft-deletes QR codes inactive for longer than `RETENTION_DAYS`:

```bash
python3 scripts/cleanup.py
```
