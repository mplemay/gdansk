from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path


class Plugin(Protocol):
    async def build(self, *, views: Path, output: Path) -> None: ...

    async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None: ...
