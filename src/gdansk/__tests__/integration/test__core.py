from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from anyio import Path as APath

from gdansk._core import Runtime, bundle


async def _wait_for_file_or_task_failure(
    task: asyncio.Task[None],
    output_path: Path,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    path = APath(output_path)
    while loop.time() < deadline:
        if await path.exists():
            return
        if task.done():
            exc = task.exception()
            message = f"bundle task ended before emitting {output_path}: {exc!r}"
            pytest.fail(message)
        await asyncio.sleep(0.05)

    message = f"timed out waiting for bundle output: {output_path}"
    pytest.fail(message)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_writes_default_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    await bundle({Path("main.tsx")})

    assert (tmp_path / ".gdansk" / "main.js").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_writes_nested_output_in_custom_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "home" / "page.tsx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const home = 1;\n", encoding="utf-8")

    await bundle({Path("home/page.tsx")}, output=Path("custom-out"))

    assert (tmp_path / "custom-out" / "home" / "page.js").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_empty_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        await bundle(set())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_non_jsx_or_tsx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.ts").write_text("export const value = 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        await bundle({Path("main.ts")})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_input_outside_cwd(tmp_path, tmp_path_factory, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside_root = tmp_path_factory.mktemp("outside")
    outside_file = outside_root / "outside.tsx"
    outside_file.write_text("export const value = 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside cwd"):
        await bundle({outside_file})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_output_collisions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.tsx").write_text("export const a = 1;\n", encoding="utf-8")
    (tmp_path / "a.jsx").write_text("export const b = 2;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="same output"):
        await bundle({Path("a.tsx"), Path("a.jsx")})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_dev_mode_can_run_in_background_and_cancel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    task = asyncio.ensure_future(bundle({Path("main.tsx")}, dev=True))
    await _wait_for_file_or_task_failure(task, tmp_path / ".gdansk" / "main.js")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_outputs_css_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "page.css").write_text("body { color: red; }\n", encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    await bundle({Path("page.tsx")})

    assert (tmp_path / ".gdansk" / "page.js").exists()
    assert (tmp_path / ".gdansk" / "page.css").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_resolves_css_package_style_exports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    package_dir = tmp_path / "node_modules" / "tw-animate-css"
    (package_dir / "dist").mkdir(parents=True, exist_ok=True)
    (package_dir / "package.json").write_text(
        """
{
  "name": "tw-animate-css",
  "exports": {
    ".": {
      "style": "./dist/tw-animate.css"
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "dist" / "tw-animate.css").write_text(
        "body { color: green; }\n",
        encoding="utf-8",
    )

    (tmp_path / "page.css").write_text('@import "tw-animate-css";\n', encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    await bundle({Path("page.tsx")})

    css_output = tmp_path / ".gdansk" / "page.css"
    assert css_output.exists()
    assert "green" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_accepts_minify_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    await bundle({Path("main.tsx")}, minify=False)

    assert (tmp_path / ".gdansk" / "main.js").exists()


@pytest.mark.integration
def test_runtime_constructs_and_evaluates_expression():
    runtime = Runtime()
    assert runtime("1 + 2") == 3


@pytest.mark.integration
def test_runtime_preserves_state_across_calls():
    runtime = Runtime()
    runtime("globalThis.counter = 1")
    assert runtime("counter += 2; counter") == 3


@pytest.mark.integration
def test_runtime_converts_nested_json_like_values():
    runtime = Runtime()
    assert runtime('({ ok: true, values: [1, { name: "gdansk" }, null] })') == {
        "ok": True,
        "values": [1, {"name": "gdansk"}, None],
    }


@pytest.mark.integration
def test_runtime_reports_execution_errors():
    runtime = Runtime()
    with pytest.raises(RuntimeError, match="Execution error"):
        runtime("throw new Error('boom')")


@pytest.mark.integration
def test_runtime_rejects_unsupported_values():
    runtime = Runtime()
    with pytest.raises(ValueError, match="Cannot deserialize value"):
        runtime("undefined")
