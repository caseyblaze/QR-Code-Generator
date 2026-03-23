import importlib

import pytest
from fastapi.testclient import TestClient

from app.storage import image_path, normalize_spec, spec_hash


def build_client(tmp_path, monkeypatch):
    storage_path = tmp_path / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)

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


def test_create_and_get_qr_code(client):
    test_client, _, _ = client
    response = test_client.post("/v1/qr_code", json={"url": "https://ex.com"})
    assert response.status_code == 200

    qr_token = response.json()["qr_token"]
    get_response = test_client.get(f"/v1/qr_code/{qr_token}")
    assert get_response.status_code == 200
    assert get_response.json()["url"] == "https://ex.com"


def test_update_and_delete_qr_code(client):
    test_client, _, _ = client
    response = test_client.post("/v1/qr_code", json={"url": "https://ex.com"})
    qr_token = response.json()["qr_token"]

    update_response = test_client.put(
        f"/v1/qr_code/{qr_token}", json={"url": "https://ex2.com"}
    )
    assert update_response.status_code == 204

    get_response = test_client.get(f"/v1/qr_code/{qr_token}")
    assert get_response.status_code == 200
    assert get_response.json()["url"] == "https://ex2.com"

    delete_response = test_client.delete(f"/v1/qr_code/{qr_token}")
    assert delete_response.status_code == 204

    missing_response = test_client.get(f"/v1/qr_code/{qr_token}")
    assert missing_response.status_code == 404


def test_redirect(client):
    test_client, _, _ = client
    response = test_client.post("/v1/qr_code", json={"url": "https://ex.com"})
    qr_token = response.json()["qr_token"]

    redirect_response = test_client.get(f"/{qr_token}", follow_redirects=False)
    assert redirect_response.status_code == 302
    assert redirect_response.headers["location"] == "https://ex.com"


def test_qr_image_generation(client):
    test_client, settings, _ = client
    response = test_client.post("/v1/qr_code", json={"url": "https://ex.com"})
    qr_token = response.json()["qr_token"]

    image_response = test_client.get(
        f"/v1/qr_code_image/{qr_token}",
        params={"dimension": 128, "color": "#000000", "border": 2},
    )
    assert image_response.status_code == 200

    image_location = image_response.json()["image_location"]
    assert image_location.startswith("http://cdn.test/qr/")

    spec = normalize_spec(128, "#000000", 2)
    hash_value = spec_hash(spec)
    path = image_path(settings.SETTINGS.storage_path, qr_token, hash_value)
    assert path.exists()


def test_invalid_url_length(client):
    test_client, _, _ = client
    long_url = "https://example.com/" + ("a" * 2048)
    response = test_client.post("/v1/qr_code", json={"url": long_url})
    assert response.status_code == 422
