"""PostCSS plugin support for css assets in gdansk pages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from os import environ, name
from subprocess import PIPE
from typing import TYPE_CHECKING, cast

from anyio import Path as APath, TemporaryDirectory

if TYPE_CHECKING:
    from pathlib import Path


class PostCSSError(RuntimeError):
    """Raised when PostCSS compilation fails."""


@dataclass(slots=True, kw_only=True)
class PostCSS:
    """Builds CSS files using postcss-cli."""

    timeout: float = 0.1

    async def __call__(self, *, pages: Path, output: Path) -> None:
        """Compile discovered CSS files in a single pass."""
        if not (css := await self._collect_css_files(output=APath(output))):
            return

        cli = await self._resolve_cli(pages=pages)

        for css_path in css:
            try:
                await self._process_css_file(css_path=css_path, cli_path=cli, pages=pages)
            except FileNotFoundError:
                continue

    async def _process_css_file(self, *, css_path: APath, cli_path: Path, pages: Path) -> None:
        if not await css_path.exists():
            raise FileNotFoundError(css_path)

        async with TemporaryDirectory() as tmp_dir_name:
            output = APath(tmp_dir_name) / "output.css"
            process = await asyncio.create_subprocess_exec(
                str(cli_path),
                str(css_path),
                "-o",
                str(output),
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

            if not await output.exists():
                msg = f"postcss did not produce output for {css_path}"
                raise PostCSSError(msg)

            compiled = await output.read_text(encoding="utf-8")
            await css_path.write_text(compiled, encoding="utf-8")

    async def _collect_css_files(self, *, output: APath) -> list[APath]:
        if not await output.exists():
            return []

        css_files = [APath(str(path)) async for path in output.rglob("*.css") if await path.is_file()]

        return cast("list[APath]", sorted(css_files, key=str))

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
