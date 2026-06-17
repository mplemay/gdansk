from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def join_url(origin: str, path: str) -> str:
    parsed = urlparse(origin)
    normalized_path = path if path.startswith("/") else f"/{path}"
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))
