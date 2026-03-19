# ruff: noqa: D100,D101,D102,D103,D105,TC001

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from os import PathLike, fspath
from pathlib import Path

from anyio import Path as APath

from gdansk._core import JsPluginRunner
from gdansk.protocol import JsPluginSpec


def _resolve_specifier(specifier: str | PathLike[str], base: Path) -> str:
    specifier = fspath(specifier)
    if specifier.startswith("file://"):
        return specifier

    path = Path(specifier)
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=True).as_uri()


def _serialize_specs(specs: list[JsPluginSpec], base: Path) -> str:
    payload = [
        {
            "specifier": _resolve_specifier(spec.specifier, base),
            "options": spec.options,
        }
        for spec in specs
    ]
    return json.dumps(payload)


@dataclass(slots=True, kw_only=True)
class JsLifecyclePlugin:
    _runner: JsPluginRunner = field(repr=False)
    poll_interval_seconds: float = field(default=0.1, kw_only=True)
    _closed: bool = field(default=False, init=False, repr=False)

    async def build(self, *, pages: Path, output: Path) -> None:
        await self._runner.build(pages=pages, output=output)

    async def watch(self, *, pages: Path, output: Path, stop_event: asyncio.Event) -> None:
        known_mtimes: dict[Path, int] = {}

        try:
            while not stop_event.is_set():
                css_files = await self._collect_css_files(output=output)
                changed = False

                for css_path in css_files:
                    css_apath = APath(css_path)
                    try:
                        current_mtime = (await css_apath.stat()).st_mtime_ns
                    except FileNotFoundError:
                        known_mtimes.pop(css_path, None)
                        continue

                    if known_mtimes.get(css_path) != current_mtime:
                        changed = True

                if css_files and (changed or not known_mtimes):
                    await self.build(pages=pages, output=output)
                    known_mtimes = {}
                    for css_path in await self._collect_css_files(output=output):
                        css_apath = APath(css_path)
                        try:
                            known_mtimes[css_path] = (await css_apath.stat()).st_mtime_ns
                        except FileNotFoundError:
                            continue

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)
                except TimeoutError:
                    continue
        finally:
            self.close()

    async def _collect_css_files(self, *, output: Path) -> list[Path]:
        output_apath = APath(output)
        if not await output_apath.exists():
            return []

        css_files = [Path(str(path)) async for path in output_apath.rglob("*.css") if await path.is_file()]
        return sorted(css_files)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._runner.close()

    def __del__(self) -> None:
        self.close()


def create_js_lifecycle_plugin(specs: list[JsPluginSpec], *, pages: Path) -> JsLifecyclePlugin:
    runner = JsPluginRunner(_serialize_specs(specs, pages))
    return JsLifecyclePlugin(_runner=runner)
