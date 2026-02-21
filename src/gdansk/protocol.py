"""Shared protocol definitions for gdansk plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path


class Plugin(Protocol):
    """Plugin interface for build and watch hooks."""

    async def build(self, *, pages: Path, output: Path) -> None:
        """Build plugin outputs into the generated assets directory."""

    async def watch(self, *, pages: Path, output: Path, stop_event: asyncio.Event) -> None:
        """Watch for source changes and update generated assets until stopped."""
