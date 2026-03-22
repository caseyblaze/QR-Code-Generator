from pathlib import Path
import hashlib
import json


def normalize_spec(dimension: int, color: str, border: int) -> dict:
    return {"border": border, "color": color, "dimension": dimension}


def spec_hash(spec: dict) -> str:
    payload = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def image_path(storage_path: Path, qr_token: str, hash_value: str) -> Path:
    return storage_path / "qr" / qr_token / f"{hash_value}.png"


def store_image(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def build_cdn_url(base_url: str, qr_token: str, hash_value: str) -> str:
    return f"{base_url.rstrip('/')}/qr/{qr_token}/{hash_value}.png"
