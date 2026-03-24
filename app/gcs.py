from functools import lru_cache
from pathlib import Path

try:
    from google.cloud import storage
except ImportError:  # pragma: no cover - optional dependency
    storage = None

from .settings import SETTINGS


def _require_storage() -> None:
    if storage is None:
        raise RuntimeError(
            "google-cloud-storage is required when GCP_BUCKET_NAME is set"
        )


@lru_cache(maxsize=1)
def _client():
    _require_storage()
    if SETTINGS.gcp_project_id:
        return storage.Client(project=SETTINGS.gcp_project_id)
    return storage.Client()


def blob_exists(bucket_name: str, object_name: str) -> bool:
    bucket = _client().bucket(bucket_name)
    return bucket.blob(object_name).exists()


def download_blob_bytes(bucket_name: str, object_name: str) -> bytes:
    bucket = _client().bucket(bucket_name)
    return bucket.blob(object_name).download_as_bytes()


def upload_path(bucket_name: str, object_name: str, path: Path) -> None:
    bucket = _client().bucket(bucket_name)
    bucket.blob(object_name).upload_from_filename(
        str(path), content_type="image/png"
    )
