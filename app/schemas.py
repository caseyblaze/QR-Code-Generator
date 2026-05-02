import ipaddress
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field, field_validator

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
_BLOCKED_HOSTS = {"localhost", "0.0.0.0"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_private_host(hostname: str) -> bool:
    if hostname.lower() in _BLOCKED_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


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

    hostname = parsed.hostname or ""
    if _is_private_host(hostname):
        raise ValueError("url must not point to a private or reserved address")

    # Normalize: lowercase scheme and host, strip default port
    scheme = parsed.scheme.lower()
    netloc = hostname.lower()
    if parsed.port and parsed.port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{netloc}:{parsed.port}"

    return urlunparse(parsed._replace(scheme=scheme, netloc=netloc))


class CreateQrRequest(BaseModel):
    url: str
    expires_at: Optional[datetime] = None

    @field_validator("url")
    @classmethod
    def validate_url_field(cls, value: str) -> str:
        return validate_url(value)


class UpdateQrRequest(BaseModel):
    url: str
    expires_at: Optional[datetime] = None

    @field_validator("url")
    @classmethod
    def validate_url_field(cls, value: str) -> str:
        return validate_url(value)


class CreateQrResponse(BaseModel):
    token: str
    short_url: str
    qr_code_url: str
    original_url: str


class UrlResponse(BaseModel):
    url: str


class ScansByDay(BaseModel):
    date: str
    count: int


class AnalyticsResponse(BaseModel):
    token: str
    total_scans: int
    scans_by_day: list[ScansByDay]


class ImageSpec(BaseModel):
    dimension: int = Field(default=256, ge=64)
    color: str = Field(default="#000000", min_length=1, max_length=32)
    border: int = Field(default=4, ge=0, le=16)

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value):
            raise ValueError("color must be a hex value like #rrggbb or #rgb")
        return value
