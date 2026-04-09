from __future__ import annotations

import socket
from urllib.parse import urlparse, urlunparse


def get_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def join_url(origin: str, path: str) -> str:
    parsed = urlparse(origin)
    normalized_path = path if path.startswith("/") else f"/{path}"
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))
