# QR Code Generator Plan

## Scope
Build a QR Code Generator service using Python + FastAPI based on the provided PDF requirements.

## Step 1: Requirements and decisions
Define scope boundaries and missing decisions.

Actions
- Confirm whether user accounts/auth are required for managing QR codes.
- Decide where QR images are stored (on-demand only vs. object storage + CDN).
- Define retention/cleanup policy for unused QR codes.

Outputs
- Documented decisions for auth, storage, and retention.

Decisions (Step 1 complete)
- No user accounts or login; management via QR token only.
- QR images are stored in object storage and served via CDN.
- Expire and delete QR codes after 7 days without clicks.

## Step 2: API contracts and data model
Define endpoints and database schema.

Actions
- Specify request/response payloads for:
  - POST /v1/qr_code
  - GET /v1/qr_code_image/:qr_token
  - GET/PUT/DELETE /v1/qr_code/:qr_token
  - GET /:qr_token (redirect)
- Draft QrCodes table schema with UNIQUE+index on qr_token.

Outputs
- API spec and database schema draft.

Draft API spec (Step 2 complete)
- POST /v1/qr_code
  - Body: { "url": "https://..." }
  - Response: { "qr_token": "abc123" }
- GET /v1/qr_code_image/:qr_token
  - Body: { "image_spec": { "dimension": 256, "color": "#000000", "border": 4 } }
  - Response: { "image_location": "https://cdn.example.com/qr/abc123/specHash.png" }
- GET /v1/qr_code/:qr_token
  - Response: { "url": "https://..." }
- PUT /v1/qr_code/:qr_token
  - Body: { "url": "https://..." }
  - Response: 204 No Content
- DELETE /v1/qr_code/:qr_token
  - Response: 204 No Content
- GET /:qr_token
  - Response: 302 redirect to original URL

Draft data model (Step 2 complete)
- Table: qr_codes
  - id (UUID, PK)
  - qr_token (string, UNIQUE, indexed)
  - url (string, not null, max 2048 ASCII chars per requirement)
  - status (enum: active, deleted)
  - created_at, updated_at
  - last_clicked_at (timestamp, for cleanup)
  - deleted_at (nullable timestamp)

## Step 3: Token generation strategy
Design unique token creation and collision handling.

Actions
- Define hash input (url + nonce + secret) and Base62 encoding.
- Decide token length to meet collision risk targets.
- Implement retry on UNIQUE constraint violation.

Outputs
- Token generation algorithm and constraints.

Draft token generation (Step 3 complete)
- Input: url + random nonce + server secret.
- Hash: SHA-256 over the input.
- Encode: Base62; take first 10 characters as qr_token.
- Collision handling: on UNIQUE constraint violation, regenerate with a new nonce.

## Step 4: QR image generation and hosting
Plan QR image creation flow and delivery.

Actions
- Choose QR library and image format.
- Decide on on-demand generation vs. pre-generation.
- If pre-generated, choose object storage and CDN strategy.

Outputs
- Image generation and hosting design.

Draft image generation (Step 4 complete)
- Library: `qrcode` with Pillow backend, output PNG.
- Storage: upload to object storage (e.g., S3) at `qr/{qr_token}/{spec_hash}.png`.
- CDN: serve public images via CDN; return the CDN URL as `image_location`.
- Cache key: `spec_hash = sha256(normalized image_spec)` to reuse identical renders.

## Step 5: Redirect behavior and performance
Define redirect flow and caching strategy.

Actions
- Use 302 redirects to allow edits/deletions.
- Add DB indexing and cache layer (e.g., Redis).
- Consider CDN caching for hot QR codes.

Outputs
- Redirect and caching plan aligned with <100ms latency target.

Draft redirect/perf (Step 5 complete)
- Redirect endpoint returns HTTP 302 to allow edits/deletions to take effect.
- Read path: check Redis cache for qr_token → url; fallback to DB; update cache.
- Update `last_clicked_at` asynchronously or in a write-behind queue to keep latency low.
- CDN used for QR image assets; optional edge caching for hot redirects if supported.

## Step 6: Scaling and operations
Outline scaling, HA, and maintenance.

Actions
- Stateless API services for horizontal scaling.
- Read replicas for read-heavy traffic.
- Cleanup jobs for expired/unused QR codes.
- Monitoring and alerting for availability and latency.

Outputs
- Scaling and ops plan.

Draft scaling/ops (Step 6 complete)
- Stateless API instances behind a load balancer for horizontal scaling.
- Primary DB with read replicas for read-heavy traffic.
- Scheduled cleanup job removes QR codes with no clicks for 7 days (marks deleted then purge).
- Monitor redirect latency, error rates, cache hit ratio, and storage/CDN availability.

## Execution order
1. Step 1
2. Step 2
3. Step 3
4. Step 4
5. Step 5
6. Step 6
