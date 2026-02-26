from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from anyio import Path as APath

from gdansk.experimental.postcss import PostCSS, PostCSSError


@pytest.mark.asyncio
async def test_call_skips_when_no_css_files(tmp_path):
    plugin = PostCSS()
    pages = tmp_path / "pages"
    output = tmp_path / "output"
    pages.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    await plugin(pages=pages, output=output)


@pytest.mark.asyncio
async def test_call_raises_when_cli_missing(tmp_path):
    plugin = PostCSS()
    pages = tmp_path / "pages"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    pages.mkdir(parents=True, exist_ok=True)

    with pytest.raises(OSError, match="postcss-cli was not found"):
        await plugin(pages=pages, output=output)


@pytest.mark.asyncio
async def test_call_rewrites_css_on_success(tmp_path, monkeypatch):
    plugin = PostCSS()
    pages = tmp_path / "pages"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    cli_path = pages / "node_modules" / ".bin" / "postcss"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text("", encoding="utf-8")

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def _fake_exec(*command: str, **kwargs: object) -> _Process:
        assert command[0] == str(cli_path)
        assert command[1] == str(css_path)
        assert command[2] == "-o"
        output_path = Path(command[3])
        await APath(output_path).write_text("body { color: blue; }\n", encoding="utf-8")
        assert kwargs["cwd"] == pages
        env = cast("dict[str, str]", kwargs["env"])
        assert env["NODE_PATH"] == str(pages / "node_modules")
        return _Process()

    monkeypatch.setattr("gdansk.experimental.postcss.asyncio.create_subprocess_exec", _fake_exec)

    await plugin(pages=pages, output=output)

    assert css_path.read_text(encoding="utf-8") == "body { color: blue; }\n"


@pytest.mark.asyncio
async def test_call_raises_on_subprocess_error(tmp_path, monkeypatch):
    plugin = PostCSS()
    pages = tmp_path / "pages"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    cli_path = pages / "node_modules" / ".bin" / "postcss"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text("", encoding="utf-8")

    class _Process:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"boom"

    async def _fake_exec(*_command: str, **_kwargs: object) -> _Process:
        return _Process()

    monkeypatch.setattr("gdansk.experimental.postcss.asyncio.create_subprocess_exec", _fake_exec)

    with pytest.raises(PostCSSError, match="boom"):
        await plugin(pages=pages, output=output)


@pytest.mark.asyncio
async def test_call_processes_css_on_each_pass(tmp_path, monkeypatch):
    plugin = PostCSS(timeout=0.01)
    pages = tmp_path / "pages"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    pages.mkdir(parents=True, exist_ok=True)

    async def _resolve_cli(self, *, pages: Path) -> Path:
        _ = self
        return pages / "postcss"

    monkeypatch.setattr(PostCSS, "_resolve_cli", _resolve_cli)

    calls: list[APath] = []

    async def _fake_process(self, *, css_path: APath, cli_path: Path, pages: Path) -> None:
        _ = self
        assert cli_path == pages / "postcss"
        calls.append(css_path)

    monkeypatch.setattr(PostCSS, "_process_css_file", _fake_process)

    await plugin(pages=pages, output=output)
    assert len(calls) == 1

    await plugin(pages=pages, output=output)
    assert len(calls) == 2

    css_path.write_text("body { color: blue; }\n", encoding="utf-8")
    await plugin(pages=pages, output=output)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_call_handles_file_removed_between_scan_and_process(tmp_path, monkeypatch):
    plugin = PostCSS(timeout=0.01)
    pages = tmp_path / "pages"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    pages.mkdir(parents=True, exist_ok=True)

    async def _resolve_cli(self, *, pages: Path) -> Path:
        _ = self
        return pages / "postcss"

    monkeypatch.setattr(PostCSS, "_resolve_cli", _resolve_cli)

    async def _disappearing_process(self, *, css_path: APath, cli_path: Path, pages: Path) -> None:
        _ = (self, cli_path, pages)
        await css_path.unlink(missing_ok=True)
        raise FileNotFoundError(css_path)

    monkeypatch.setattr(PostCSS, "_process_css_file", _disappearing_process)

    await plugin(pages=pages, output=output)
    await plugin(pages=pages, output=output)
