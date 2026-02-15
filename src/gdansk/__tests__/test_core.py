import asyncio
from pathlib import Path

import pytest

from gdansk import bundle


async def _wait_for_file_or_task_failure(
    task: "asyncio.Task[None]",
    output_path: Path,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        if output_path.exists():
            return
        if task.done():
            exc = task.exception()
            raise AssertionError(
                f"bundle task ended before emitting {output_path}: {exc!r}",
            )
        await asyncio.sleep(0.05)

    raise AssertionError(f"timed out waiting for bundle output: {output_path}")


@pytest.mark.asyncio
async def test_bundle_writes_default_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    await bundle({Path("main.tsx")})

    assert (tmp_path / ".gdansk" / "main.js").exists()


@pytest.mark.asyncio
async def test_bundle_writes_nested_output_in_custom_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "home" / "page.tsx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const home = 1;\n", encoding="utf-8")

    await bundle({Path("home/page.tsx")}, output=Path("custom-out"))

    assert (tmp_path / "custom-out" / "home" / "page.js").exists()


@pytest.mark.asyncio
async def test_bundle_rejects_empty_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        await bundle(set())


@pytest.mark.asyncio
async def test_bundle_rejects_non_jsx_or_tsx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.ts").write_text("export const value = 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        await bundle({Path("main.ts")})


@pytest.mark.asyncio
async def test_bundle_rejects_input_outside_cwd(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    outside_root = tmp_path_factory.mktemp("outside")
    outside_file = outside_root / "outside.tsx"
    outside_file.write_text("export const value = 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside cwd"):
        await bundle({outside_file})


@pytest.mark.asyncio
async def test_bundle_rejects_output_collisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.tsx").write_text("export const a = 1;\n", encoding="utf-8")
    (tmp_path / "a.jsx").write_text("export const b = 2;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="same output"):
        await bundle({Path("a.tsx"), Path("a.jsx")})


@pytest.mark.asyncio
async def test_bundle_dev_mode_can_run_in_background_and_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    task = asyncio.create_task(bundle({Path("main.tsx")}, dev=True))
    await _wait_for_file_or_task_failure(task, tmp_path / ".gdansk" / "main.js")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
