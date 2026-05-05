from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import isawaitable
from pathlib import PurePosixPath
from typing import cast, overload
from urllib.parse import urlparse, urlunparse

type MaybeAwaitable[T] = T | Awaitable[T]


@overload
def maybe_awaitable[**P, T](callback: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]: ...


@overload
def maybe_awaitable[**P, T](callback: Callable[P, T]) -> Callable[P, Awaitable[T]]: ...


def maybe_awaitable[**P, T](callback: Callable[P, MaybeAwaitable[T]]) -> Callable[P, Awaitable[T]]:
    @wraps(callback)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        result = callback(*args, **kwargs)
        if isawaitable(result):
            return await cast("Awaitable[T]", result)

        return result

    return wrapper


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
