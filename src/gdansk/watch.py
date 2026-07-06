from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from watchfiles import DefaultFilter, awatch

if TYPE_CHECKING:
    from gdansk.vite import Vite

logger = logging.getLogger(__name__)

DEBOUNCE_MS: Final[int] = 300


def _watch_filter(vite: Vite) -> DefaultFilter:
    return DefaultFilter(ignore_paths=[vite.build_directory_path])


async def watch_and_rebuild(vite: Vite) -> None:
    async for _changes in awatch(vite.root, debounce=DEBOUNCE_MS, watch_filter=_watch_filter(vite)):
        try:
            await vite.build()
            vite.load_manifest()
        except Exception:
            logger.exception("Widget rebuild failed")
