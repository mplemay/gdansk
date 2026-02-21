"""PostCSS plugin support for css assets in gdansk pages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from os import environ, name
from pathlib import Path
from subprocess import PIPE
from tempfile import TemporaryDirectory

from anyio import Path as APath


class PostCSSError(RuntimeError):
    """Raised when PostCSS compilation fails."""


@dataclass(slots=True, kw_only=True)
class PostCSS:
    """Builds and watches CSS files using postcss-cli."""

    poll_interval_seconds: float = 0.1

    async def build(self, *, pages: Path, output: Path) -> None:
        """Compile all discovered CSS files once."""
        css_files = await self._collect_css_files(output=output)
        if not css_files:
            return
        cli_path = await self._resolve_cli(pages=pages)
        for css_path in css_files:
            await self._process_css_file(css_path=css_path, cli_path=cli_path, pages=pages)

    async def watch(self, *, pages: Path, output: Path, stop_event: asyncio.Event) -> None:
        """Watch CSS files and recompile when they change."""
        cli_path = await self._resolve_cli(pages=pages)
        known_mtimes: dict[Path, int] = {}

        while not stop_event.is_set():
            for css_path in await self._collect_css_files(output=output):
                css_apath = APath(css_path)
                try:
                    current_mtime = (await css_apath.stat()).st_mtime_ns
                except FileNotFoundError:
                    known_mtimes.pop(css_path, None)
                    continue

                if known_mtimes.get(css_path) == current_mtime:
                    continue

                try:
                    await self._process_css_file(css_path=css_path, cli_path=cli_path, pages=pages)
                except FileNotFoundError:
                    known_mtimes.pop(css_path, None)
                    continue

                try:
                    known_mtimes[css_path] = (await css_apath.stat()).st_mtime_ns
                except FileNotFoundError:
                    known_mtimes.pop(css_path, None)

            known_mtimes = {
                tracked_path: tracked_mtime
                for tracked_path, tracked_mtime in known_mtimes.items()
                if await APath(tracked_path).exists()
            }

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)
            except TimeoutError:
                continue

    async def _process_css_file(self, *, css_path: Path, cli_path: Path, pages: Path) -> None:
        css_apath = APath(css_path)
        if not await css_apath.exists():
            raise FileNotFoundError(css_path)

        with TemporaryDirectory() as tmp_dir_name:
            output_path = Path(tmp_dir_name) / "output.css"
            process = await asyncio.create_subprocess_exec(
                str(cli_path),
                str(css_path),
                "-o",
                str(output_path),
                stdout=PIPE,
                stderr=PIPE,
                cwd=pages,
                env={
                    **environ,
                    "NODE_PATH": str(pages / "node_modules"),
                },
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_detail = stderr.decode().strip() or stdout.decode().strip() or "unknown postcss error"
                msg = f"postcss failed for {css_path}: {error_detail}"
                raise PostCSSError(msg)

            output_apath = APath(output_path)
            if not await output_apath.exists():
                msg = f"postcss did not produce output for {css_path}"
                raise PostCSSError(msg)

            compiled_css = await output_apath.read_text(encoding="utf-8")
            await css_apath.write_text(compiled_css, encoding="utf-8")

    async def _collect_css_files(self, *, output: Path) -> list[Path]:
        output_apath = APath(output)
        if not await output_apath.exists():
            return []

        css_files = [Path(str(path)) async for path in output_apath.rglob("*.css") if await path.is_file()]

        return sorted(css_files)

    async def _resolve_cli(self, *, pages: Path) -> Path:
        bin_dir = pages / "node_modules" / ".bin"
        candidates = [bin_dir / "postcss"]
        if name == "nt":
            candidates = [bin_dir / "postcss.cmd", bin_dir / "postcss.exe", *candidates]

        for candidate in candidates:
            if await APath(candidate).is_file():
                return candidate

        msg = (
            "postcss-cli was not found in views/node_modules/.bin. "
            "Install it with `npm install -D postcss postcss-cli` in your views directory."
        )
        raise OSError(msg)
