from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path
    storage_path: Path
    cdn_base_url: str
    public_base_url: str
    token_secret: str
    token_length: int
    retention_days: int
    cache_ttl_seconds: int
    default_dimension: int
    default_color: str
    default_border: int
    max_dimension: int


def load_settings() -> Settings:
    return Settings(
        db_path=Path(os.getenv("DB_PATH", "data/qr_codes.db")),
        storage_path=Path(os.getenv("STORAGE_PATH", "storage")),
        cdn_base_url=os.getenv("CDN_BASE_URL", "http://localhost:8000/static"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"),
        token_secret=os.getenv("TOKEN_SECRET", "dev-secret"),
        token_length=int(os.getenv("TOKEN_LENGTH", "10")),
        retention_days=int(os.getenv("RETENTION_DAYS", "7")),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "300")),
        default_dimension=int(os.getenv("DEFAULT_DIMENSION", "256")),
        default_color=os.getenv("DEFAULT_COLOR", "#000000"),
        default_border=int(os.getenv("DEFAULT_BORDER", "4")),
        max_dimension=int(os.getenv("MAX_DIMENSION", "1024")),
    )


SETTINGS = load_settings()
