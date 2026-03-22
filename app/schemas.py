from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse


def validate_url(value: str) -> str:
    if len(value) > 2048:
        raise ValueError("url must be at most 2048 characters")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("url must be ASCII") from exc

    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("url must include http/https scheme and host")
    return value


class CreateQrRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url_field(cls, value: str) -> str:
        return validate_url(value)


class UpdateQrRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url_field(cls, value: str) -> str:
        return validate_url(value)


class CreateQrResponse(BaseModel):
    qr_token: str


class UrlResponse(BaseModel):
    url: str


class ImageSpec(BaseModel):
    dimension: int = Field(default=256, ge=64)
    color: str = Field(default="#000000", min_length=1, max_length=32)
    border: int = Field(default=4, ge=0, le=16)
