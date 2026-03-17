from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from anyio import Path as APath

from gdansk._core import bundle
from gdansk.core import Page

WORKER_FIXTURE = Path(__file__).parent.parent / "fixtures" / "tailwind_worker.py"


def _use_stub_tailwind_worker(monkeypatch) -> None:
    monkeypatch.setenv("GDANSK_TAILWIND_NODE_BINARY", sys.executable)
    monkeypatch.setenv("GDANSK_TAILWIND_WORKER_PATH", str(WORKER_FIXTURE))


async def _wait_for_css_contains(
    task: asyncio.Future[object] | asyncio.Task[None],
    css_path: Path,
    expected: str,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    css_apath = APath(css_path)
    while loop.time() < deadline:
        if await css_apath.exists():
            css = await css_apath.read_text(encoding="utf-8")
            if expected in css:
                return
        if task.done():
            exc = task.exception()
            pytest.fail(f"bundle task ended before css contained {expected!r}: {exc!r}")
        await asyncio.sleep(0.05)

    pytest.fail(f"timed out waiting for css output to contain {expected!r}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tailwind_build_transforms_root_css(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _use_stub_tailwind_worker(monkeypatch)
    (tmp_path / "content.html").write_text(
        '<div class="text-red-500 bg-blue-500"></div>\n',
        encoding="utf-8",
    )
    (tmp_path / "page.css").write_text('@import "tailwindcss";\n', encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    await bundle([Page(path=Path("page.tsx"))], tailwind=True)

    css_output = (tmp_path / ".gdansk" / "page.css").read_text(encoding="utf-8")
    assert "--tw-text-red-500" in css_output
    assert "--tw-bg-blue-500" in css_output


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tailwind_enabled_projects_keep_plain_css_passthrough(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _use_stub_tailwind_worker(monkeypatch)
    (tmp_path / "page.css").write_text("body { color: red; }\n", encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    await bundle([Page(path=Path("page.tsx"))], tailwind=True)

    assert (tmp_path / ".gdansk" / "page.css").read_text(encoding="utf-8") == "body{color:red}\n"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tailwind_dev_rebuilds_when_scanned_html_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _use_stub_tailwind_worker(monkeypatch)
    html_path = tmp_path / "content.html"
    html_path.write_text('<div class="text-red-500"></div>\n', encoding="utf-8")
    (tmp_path / "page.css").write_text('@import "tailwindcss";\n', encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    task = asyncio.ensure_future(bundle([Page(path=Path("page.tsx"))], dev=True, tailwind=True))
    css_output = tmp_path / ".gdansk" / "page.css"
    await _wait_for_css_contains(task, css_output, "--tw-text-red-500")

    html_path.write_text('<div class="text-green-500"></div>\n', encoding="utf-8")
    await _wait_for_css_contains(task, css_output, "--tw-text-green-500")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tailwind_dev_rebuilds_when_config_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _use_stub_tailwind_worker(monkeypatch)
    (tmp_path / "tailwind.config.js").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "page.css").write_text('@import "tailwindcss";\n', encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    task = asyncio.ensure_future(bundle([Page(path=Path("page.tsx"))], dev=True, tailwind=True))
    css_output = tmp_path / ".gdansk" / "page.css"
    await _wait_for_css_contains(task, css_output, "--tw-config-alpha")

    (tmp_path / "tailwind.config.js").write_text("beta\n", encoding="utf-8")
    await _wait_for_css_contains(task, css_output, "--tw-config-beta")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tailwind_missing_runtime_dependencies_raise_actionable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDANSK_TAILWIND_NODE_BINARY", raising=False)
    monkeypatch.delenv("GDANSK_TAILWIND_WORKER_PATH", raising=False)
    (tmp_path / "page.css").write_text('@import "tailwindcss";\n', encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match=r"Tailwind support requires `tailwindcss`, `@tailwindcss/node`, and `@tailwindcss/oxide`",
    ):
        await bundle([Page(path=Path("page.tsx"))], tailwind=True)
