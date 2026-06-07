from __future__ import annotations

import os
import platform
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import maturin

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_RUSTFLAGS_SEPARATOR = "\x1f"
_MACOS_ARM64_PYO3_RUSTFLAGS = (
    "-C",
    "link-arg=-undefined",
    "-C",
    "link-arg=dynamic_lookup",
)


def _is_macos_arm64() -> bool:
    return platform.system() == "Darwin" and platform.machine().lower() in {
        "arm64",
        "aarch64",
    }


@contextmanager
def _standalone_python_build_rustflags() -> Iterator[None]:
    previous_rustflags = os.environ.get("CARGO_ENCODED_RUSTFLAGS")
    had_rustflags = "CARGO_ENCODED_RUSTFLAGS" in os.environ

    if _is_macos_arm64():
        # This crate is a standalone Python extension. Avoid inheriting the
        # repo-level Deno CLI linker choice, which Apple clang rejects.
        os.environ["CARGO_ENCODED_RUSTFLAGS"] = _RUSTFLAGS_SEPARATOR.join(
            _MACOS_ARM64_PYO3_RUSTFLAGS,
        )

    try:
        yield
    finally:
        if had_rustflags and previous_rustflags is not None:
            os.environ["CARGO_ENCODED_RUSTFLAGS"] = previous_rustflags
        else:
            os.environ.pop("CARGO_ENCODED_RUSTFLAGS", None)


def _with_standalone_rustflags[**P, T](func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    with _standalone_python_build_rustflags():
        return func(*args, **kwargs)


def build_wheel(*args: Any, **kwargs: Any) -> str:
    return _with_standalone_rustflags(maturin.build_wheel, *args, **kwargs)


def build_editable(*args: Any, **kwargs: Any) -> str:
    return _with_standalone_rustflags(maturin.build_editable, *args, **kwargs)


def build_sdist(*args: Any, **kwargs: Any) -> str:
    return _with_standalone_rustflags(maturin.build_sdist, *args, **kwargs)


def prepare_metadata_for_build_wheel(*args: Any, **kwargs: Any) -> str:
    return _with_standalone_rustflags(
        maturin.prepare_metadata_for_build_wheel,
        *args,
        **kwargs,
    )


def prepare_metadata_for_build_editable(*args: Any, **kwargs: Any) -> str:
    return _with_standalone_rustflags(
        maturin.prepare_metadata_for_build_editable,
        *args,
        **kwargs,
    )


def get_requires_for_build_wheel(*args: Any, **kwargs: Any) -> list[str]:
    return maturin.get_requires_for_build_wheel(*args, **kwargs)


def get_requires_for_build_editable(*args: Any, **kwargs: Any) -> list[str]:
    return maturin.get_requires_for_build_editable(*args, **kwargs)


def get_requires_for_build_sdist(*args: Any, **kwargs: Any) -> list[str]:
    return maturin.get_requires_for_build_sdist(*args, **kwargs)
