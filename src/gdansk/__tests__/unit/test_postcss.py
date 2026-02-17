from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from anyio import Path as APath

from gdansk.experimental.postcss import PostCSS, PostCSSError


async def _wait_until(predicate, *, timeout_seconds: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for condition")


@pytest.mark.asyncio
async def test_build_skips_when_no_css_files(tmp_path):
    plugin = PostCSS()
    views = tmp_path / "views"
    output = tmp_path / "output"
    views.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    await plugin.build(views=views, output=output)


@pytest.mark.asyncio
async def test_build_raises_when_cli_missing(tmp_path):
    plugin = PostCSS()
    views = tmp_path / "views"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    views.mkdir(parents=True, exist_ok=True)

    with pytest.raises(OSError, match="postcss-cli was not found"):
        await plugin.build(views=views, output=output)


@pytest.mark.asyncio
async def test_build_rewrites_css_on_success(tmp_path, monkeypatch):
    plugin = PostCSS()
    views = tmp_path / "views"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    cli_path = views / "node_modules" / ".bin" / "postcss"
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
        assert kwargs["cwd"] == views
        env = cast("dict[str, str]", kwargs["env"])
        assert env["NODE_PATH"] == str(views / "node_modules")
        return _Process()

    monkeypatch.setattr("gdansk.experimental.postcss.asyncio.create_subprocess_exec", _fake_exec)

    await plugin.build(views=views, output=output)

    assert css_path.read_text(encoding="utf-8") == "body { color: blue; }\n"


@pytest.mark.asyncio
async def test_build_raises_on_subprocess_error(tmp_path, monkeypatch):
    plugin = PostCSS()
    views = tmp_path / "views"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    cli_path = views / "node_modules" / ".bin" / "postcss"
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
        await plugin.build(views=views, output=output)


@pytest.mark.asyncio
async def test_watch_processes_changed_css_and_skips_unchanged(tmp_path, monkeypatch):
    plugin = PostCSS(poll_interval_seconds=0.01)
    views = tmp_path / "views"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    views.mkdir(parents=True, exist_ok=True)

    def _resolve_cli(self, *, views: Path) -> Path:
        _ = self
        return views / "postcss"

    monkeypatch.setattr(PostCSS, "_resolve_cli", _resolve_cli)

    calls: list[Path] = []

    async def _fake_process(self, *, css_path: Path, cli_path: Path, views: Path) -> None:
        _ = self
        assert cli_path == views / "postcss"
        calls.append(css_path)

    monkeypatch.setattr(PostCSS, "_process_css_file", _fake_process)

    stop_event = asyncio.Event()
    task = asyncio.create_task(plugin.watch(views=views, output=output, stop_event=stop_event))
    await _wait_until(lambda: len(calls) >= 1)
    initial_calls = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == initial_calls

    css_path.write_text("body { color: blue; }\n", encoding="utf-8")
    await _wait_until(lambda: len(calls) == initial_calls + 1)

    stop_event.set()
    await task


@pytest.mark.asyncio
async def test_watch_handles_file_removed_between_scan_and_process(tmp_path, monkeypatch):
    plugin = PostCSS(poll_interval_seconds=0.01)
    views = tmp_path / "views"
    output = tmp_path / "output"
    css_path = output / "apps" / "page.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("body { color: red; }\n", encoding="utf-8")
    views.mkdir(parents=True, exist_ok=True)

    def _resolve_cli(self, *, views: Path) -> Path:
        _ = self
        return views / "postcss"

    monkeypatch.setattr(PostCSS, "_resolve_cli", _resolve_cli)

    async def _disappearing_process(self, *, css_path: Path, cli_path: Path, views: Path) -> None:
        _ = (self, cli_path, views)
        await APath(css_path).unlink(missing_ok=True)
        raise FileNotFoundError(css_path)

    monkeypatch.setattr(PostCSS, "_process_css_file", _disappearing_process)

    stop_event = asyncio.Event()
    task = asyncio.create_task(plugin.watch(views=views, output=output, stop_event=stop_event))
    await asyncio.sleep(0.05)
    assert not task.done()
    stop_event.set()
    await task
