"""Shared protocol definitions for gdansk plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class Plugin(Protocol):
    """Plugin interface for one-pass build hooks."""

    timeout: float

    async def __call__(self, *, pages: Path, output: Path) -> None:
        """Run one non-blocking plugin pass."""
