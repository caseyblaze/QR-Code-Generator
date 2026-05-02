import importlib

import pytest
from fastapi.testclient import TestClient

from app.storage import image_path, normalize_spec, spec_hash


def build_client(tmp_path, monkeypatch):
    storage_path = tmp_path / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "qr.db"))
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("CDN_BASE_URL", "http://cdn.test")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_LENGTH", "8")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("RETENTION_DAYS", "7")

    import app.settings as settings
    import app.db as db
    import app.main as main

    importlib.reload(settings)
    importlib.reload(db)
    importlib.reload(main)

    return TestClient(main.app), settings, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_client, settings, main = build_client(tmp_path, monkeypatch)
    with test_client:
        yield test_client, settings, main


def test_create_response_shape(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert body["original_url"] == "https://ex.com"
    assert body["short_url"].endswith(f"/r/{body['token']}")
    assert body["qr_code_url"].endswith(f"/api/qr/{body['token']}/image")


def test_create_and_get_qr_code(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    assert response.status_code == 200

    token = response.json()["token"]
    get_response = test_client.get(f"/api/qr/{token}")
    assert get_response.status_code == 200
    assert get_response.json()["url"] == "https://ex.com"


def test_update_and_delete_qr_code(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    update_response = test_client.patch(
        f"/api/qr/{token}", json={"url": "https://ex2.com"}
    )
    assert update_response.status_code == 204

    get_response = test_client.get(f"/api/qr/{token}")
    assert get_response.status_code == 200
    assert get_response.json()["url"] == "https://ex2.com"

    delete_response = test_client.delete(f"/api/qr/{token}")
    assert delete_response.status_code == 204

    missing_response = test_client.get(f"/api/qr/{token}")
    assert missing_response.status_code == 404


def test_patch_only_expires_at(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    patch_response = test_client.patch(
        f"/api/qr/{token}", json={"expires_at": "2099-01-01T00:00:00Z"}
    )
    assert patch_response.status_code == 204

    get_response = test_client.get(f"/api/qr/{token}")
    assert get_response.status_code == 200
    assert get_response.json()["url"] == "https://ex.com"


def test_patch_clear_expires_at(client):
    test_client, _, _ = client
    response = test_client.post(
        "/api/qr/create",
        json={"url": "https://ex.com", "expires_at": "2000-01-01T00:00:00Z"},
    )
    token = response.json()["token"]

    redirect = test_client.get(f"/r/{token}", follow_redirects=False)
    assert redirect.status_code == 410

    patch_response = test_client.patch(f"/api/qr/{token}", json={"expires_at": None})
    assert patch_response.status_code == 204

    redirect = test_client.get(f"/r/{token}", follow_redirects=False)
    assert redirect.status_code == 302


def test_patch_requires_at_least_one_field(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    patch_response = test_client.patch(f"/api/qr/{token}", json={})
    assert patch_response.status_code == 422


def test_redirect(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    redirect_response = test_client.get(f"/r/{token}", follow_redirects=False)
    assert redirect_response.status_code == 302
    assert redirect_response.headers["location"] == "https://ex.com"


def test_redirect_after_update(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    test_client.patch(f"/api/qr/{token}", json={"url": "https://new-url.com"})

    redirect_response = test_client.get(f"/r/{token}", follow_redirects=False)
    assert redirect_response.status_code == 302
    assert redirect_response.headers["location"] == "https://new-url.com"


def test_redirect_deleted_returns_410(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    test_client.delete(f"/api/qr/{token}")

    redirect_response = test_client.get(f"/r/{token}", follow_redirects=False)
    assert redirect_response.status_code == 410


def test_redirect_nonexistent_returns_404(client):
    test_client, _, _ = client
    redirect_response = test_client.get("/r/INVALID_TOKEN_XYZ", follow_redirects=False)
    assert redirect_response.status_code == 404


def test_redirect_expired_returns_410(client):
    test_client, _, _ = client
    # expires_at in the past
    response = test_client.post(
        "/api/qr/create",
        json={"url": "https://ex.com", "expires_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    token = response.json()["token"]

    redirect_response = test_client.get(f"/r/{token}", follow_redirects=False)
    assert redirect_response.status_code == 410


def test_qr_image_returns_png(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    image_response = test_client.get(f"/api/qr/{token}/image")
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert image_response.content


def test_qr_image_generation(client):
    test_client, settings, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    image_response = test_client.get(
        f"/api/qr/{token}/image",
        params={"dimension": 128, "color": "#000000", "border": 2},
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")

    spec = normalize_spec(128, "#000000", 2)
    hash_value = spec_hash(spec)
    path = image_path(settings.SETTINGS.storage_path, token, hash_value)
    assert path.exists()


def test_analytics(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "https://ex.com"})
    token = response.json()["token"]

    # Trigger a few redirects to generate scan data
    for _ in range(3):
        test_client.get(f"/r/{token}", follow_redirects=False)

    analytics_response = test_client.get(f"/api/qr/{token}/analytics")
    assert analytics_response.status_code == 200
    body = analytics_response.json()
    assert body["token"] == token
    assert body["total_scans"] == 3
    assert len(body["scans_by_day"]) == 1
    assert body["scans_by_day"][0]["count"] == 3


def test_invalid_url_length(client):
    test_client, _, _ = client
    long_url = "https://example.com/" + ("a" * 2048)
    response = test_client.post("/api/qr/create", json={"url": long_url})
    assert response.status_code == 422


def test_url_normalization(client):
    test_client, _, _ = client
    response = test_client.post("/api/qr/create", json={"url": "HTTPS://Example.COM/path"})
    assert response.status_code == 200
    assert response.json()["original_url"] == "https://example.com/path"


def test_private_ip_blocked(client):
    test_client, _, _ = client
    for url in ["http://localhost/test", "http://127.0.0.1/", "http://192.168.1.1/"]:
        response = test_client.post("/api/qr/create", json={"url": url})
        assert response.status_code == 422, f"Expected 422 for {url}"


def test_verification_flow(client):
    test_client, _, _ = client

    # 1. Create a QR code → 200, returns expected fields
    resp = test_client.post("/api/qr/create", json={"url": "https://example.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert {"token", "short_url", "qr_code_url", "original_url"} <= body.keys()
    assert body["original_url"] == "https://example.com"
    token = body["token"]
    assert body["short_url"].endswith(f"/r/{token}")
    assert body["qr_code_url"].endswith(f"/api/qr/{token}/image")

    # 2. Redirect → 302
    resp = test_client.get(f"/r/{token}", follow_redirects=False)
    assert resp.status_code == 302

    # 3. Get info → 200, returns token metadata
    resp = test_client.get(f"/api/qr/{token}")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com"

    # 4. Update target URL → 200/204
    resp = test_client.patch(f"/api/qr/{token}", json={"url": "https://new-url.com"})
    assert resp.status_code in (200, 204)

    # 5. Redirect now goes to new URL
    resp = test_client.get(f"/r/{token}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://new-url.com"

    # 6. Delete → 200/204
    resp = test_client.delete(f"/api/qr/{token}")
    assert resp.status_code in (200, 204)

    # 7. Redirect after delete → 410
    resp = test_client.get(f"/r/{token}", follow_redirects=False)
    assert resp.status_code == 410

    # 8. Non-existent token → 404
    resp = test_client.get("/r/INVALID", follow_redirects=False)
    assert resp.status_code == 404

    # 9. QR code image → 200 image/png
    resp2 = test_client.post("/api/qr/create", json={"url": "https://example.com"})
    token2 = resp2.json()["token"]
    resp = test_client.get(f"/api/qr/{token2}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    # 10. Analytics → 200, returns expected shape
    resp = test_client.get(f"/api/qr/{token2}/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] == token2
    assert "total_scans" in body
    assert "scans_by_day" in body
    assert isinstance(body["total_scans"], int)
    assert isinstance(body["scans_by_day"], list)
