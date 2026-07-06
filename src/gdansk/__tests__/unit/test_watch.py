from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from watchfiles import Change

from gdansk.__tests__.unit.conftest import write_manifest
from gdansk.vite import Vite
from gdansk.watch import _watch_filter, watch_and_rebuild

if TYPE_CHECKING:
    from pathlib import Path


async def test_build_does_not_clear_loaded_manifest(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    vite = Vite(views_path)
    write_manifest(views_path, script='console.log("initial");\n')
    vite.load_manifest()

    async def fake_run_widget_command(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("gdansk.vite.run_widget_command", fake_run_widget_command)

    await vite.build()

    assert 'console.log("initial");' in vite.require_manifest().widgets["hello"].html


def test_watch_filter_ignores_build_output(views_path: Path):
    vite = Vite(views_path)
    watch_filter = _watch_filter(vite)
    build_manifest = vite.build_directory_path / "gdansk-manifest.json"
    widget_file = vite.widgets_root / "hello" / "widget.tsx"

    assert watch_filter(Change.modified, str(build_manifest)) is False
    assert watch_filter(Change.modified, str(widget_file)) is True


async def test_watch_and_rebuild_reloads_manifest_on_change(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    vite = Vite(views_path)
    build_calls = 0

    async def fake_build() -> None:
        nonlocal build_calls
        build_calls += 1
        write_manifest(
            views_path,
            script=f'console.log("build-{build_calls}");\n',
        )

    async def fake_awatch(*_args: object, **_kwargs: object):
        yield {1}
        await asyncio.Event().wait()

    monkeypatch.setattr(vite, "build", fake_build)
    monkeypatch.setattr("gdansk.watch.awatch", fake_awatch)

    task = asyncio.create_task(watch_and_rebuild(vite))
    await asyncio.sleep(0)

    assert build_calls == 1
    assert 'console.log("build-1");' in vite.load_manifest().widgets["hello"].html

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_watch_and_rebuild_keeps_manifest_on_build_failure(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    vite = Vite(views_path)
    write_manifest(views_path, script='console.log("initial");\n')
    vite.load_manifest()
    build_calls = 0

    async def fake_run_widget_command(*_args: object, **_kwargs: object) -> None:
        nonlocal build_calls
        build_calls += 1
        msg = "build failed"
        raise RuntimeError(msg)

    async def fake_awatch(*_args: object, **_kwargs: object):
        yield {1}
        await asyncio.Event().wait()

    monkeypatch.setattr("gdansk.vite.run_widget_command", fake_run_widget_command)
    monkeypatch.setattr("gdansk.watch.awatch", fake_awatch)

    task = asyncio.create_task(watch_and_rebuild(vite))
    await asyncio.sleep(0)

    assert build_calls == 1
    assert 'console.log("initial");' in vite.require_manifest().widgets["hello"].html

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
