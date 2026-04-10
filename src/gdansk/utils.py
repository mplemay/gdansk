from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse, urlunparse


def join_url(origin: str, path: str) -> str:
    parsed = urlparse(origin)
    normalized_path = path if path.startswith("/") else f"/{path}"
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def join_url_path(base: str, path: str) -> str:
    parsed = urlparse(base)
    segments = [part for part in PurePosixPath(parsed.path).parts if part not in {"", "/"}]
    suffix = [part for part in PurePosixPath(path).parts if part not in {"", "/"}]
    normalized_path = PurePosixPath("/", *segments, *suffix).as_posix()
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))
