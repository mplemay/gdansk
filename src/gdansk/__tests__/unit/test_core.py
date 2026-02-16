from __future__ import annotations

import asyncio
import dataclasses
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from gdansk.core import Amber

if TYPE_CHECKING:
    from gdansk.metadata import Metadata

# --- __post_init__ + paths property ---


def test_valid_construction(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    assert amber.mcp is mock_mcp
    assert amber.views == views_dir


def test_raises_when_views_not_directory(mock_mcp, views_dir):
    file_path = views_dir / "simple.tsx"
    with pytest.raises(ValueError, match="does not exist"):
        Amber(mcp=mock_mcp, views=file_path)


def test_raises_when_views_missing(mock_mcp, tmp_path):
    missing = tmp_path / "nonexistent"
    with pytest.raises(ValueError, match="does not exist"):
        Amber(mcp=mock_mcp, views=missing)


def test_raises_when_output_has_suffix(mock_mcp, views_dir):
    with pytest.raises(ValueError, match="does not exist"):
        Amber(mcp=mock_mcp, views=views_dir, output=Path("out.txt"))


def test_default_output(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    assert amber.output == Path.cwd() / ".gdansk"


def test_paths_empty_initially(amber):
    assert amber.paths == frozenset()


def test_frozen_dataclass(amber):
    with pytest.raises(dataclasses.FrozenInstanceError):
        amber.mcp = None


# --- __call__ context manager ---


def test_noop_when_no_paths_registered(amber):
    with patch("gdansk.core.bundle") as mock_bundle, amber():
        pass
    mock_bundle.assert_not_called()


@pytest.mark.usefixtures("views_dir")
def test_blocking_calls_bundle(amber):
    amber._paths.add(Path("simple.tsx"))

    called = False

    async def _fake_bundle(**_kwargs: object):
        nonlocal called
        called = True

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert called


@pytest.mark.usefixtures("views_dir")
def test_non_blocking_runs_in_background_thread(amber):
    amber._paths.add(Path("simple.tsx"))
    threads_during: list[list[threading.Thread]] = []

    async def _fake_bundle(**_kwargs: object):
        pass

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=False):
        threads_during.append(
            [t for t in threading.enumerate() if t.daemon and t.is_alive()],
        )

    assert len(threads_during[0]) >= 1


@pytest.mark.usefixtures("views_dir")
def test_passes_dev_flag(amber):
    amber._paths.add(Path("simple.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=True):
        pass

    assert captured[-1]["dev"] is True

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=False):
        pass

    assert captured[-1]["dev"] is False


def test_resolves_relative_output_to_absolute(mock_mcp, views_dir, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    amber = Amber(mcp=mock_mcp, views=views_dir, output=Path("rel-out"))
    amber._paths.add(Path("simple.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["output"] == tmp_path / "rel-out"
    assert captured[-1]["output"].is_absolute()


def test_absolute_output_unchanged(mock_mcp, views_dir, tmp_path):
    abs_output = tmp_path / "abs-out"
    amber = Amber(mcp=mock_mcp, views=views_dir, output=abs_output)
    amber._paths.add(Path("simple.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["output"] == abs_output


def test_passes_views_as_cwd(amber, views_dir):
    amber._paths.add(Path("simple.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["cwd"] == views_dir


@pytest.mark.usefixtures("views_dir")
def test_passes_registered_paths(amber):
    amber._paths.add(Path("simple.tsx"))
    amber._paths.add(Path("nested/page.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["paths"] == {Path("simple.tsx"), Path("nested/page.tsx")}


@pytest.mark.usefixtures("views_dir")
def test_cancels_task_on_exit(amber):
    amber._paths.add(Path("simple.tsx"))

    cancel_called = threading.Event()

    async def _slow_bundle(**_kwargs: object):
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            cancel_called.set()
            raise

    with patch("gdansk.core.bundle", _slow_bundle), amber(blocking=False):
        pass

    assert cancel_called.wait(timeout=5)


@pytest.mark.usefixtures("views_dir")
def test_closes_loop_on_exit(amber):
    amber._paths.add(Path("simple.tsx"))

    loops: list[asyncio.AbstractEventLoop] = []

    original_new_event_loop = asyncio.new_event_loop

    def _capture_loop():
        loop = original_new_event_loop()
        loops.append(loop)
        return loop

    async def _fake_bundle(**_kwargs: object):
        pass

    with (
        patch("gdansk.core.asyncio.new_event_loop", _capture_loop),
        patch("gdansk.core.bundle", _fake_bundle),
        amber(blocking=True),
    ):
        pass

    assert len(loops) == 1
    assert loops[0].is_closed()


# --- tool() decorator ---


def test_rejects_non_tsx_jsx(amber):
    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        amber.tool(Path("invalid.ts"))

    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        amber.tool(Path("page.vue"))


def test_accepts_tsx(amber):
    decorator = amber.tool(Path("simple.tsx"))
    assert callable(decorator)


def test_accepts_jsx(mock_mcp, views_dir):
    (views_dir / "app.jsx").write_text("export const app = 1;\n", encoding="utf-8")
    amber = Amber(mcp=mock_mcp, views=views_dir)
    decorator = amber.tool(Path("app.jsx"))
    assert callable(decorator)


def test_raises_when_file_not_found(amber):
    with pytest.raises(FileNotFoundError, match="was not found"):
        amber.tool(Path("missing.tsx"))


def test_adds_path_to_paths(amber):
    assert Path("simple.tsx") not in amber.paths

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    assert Path("simple.tsx") in amber.paths


def test_uri_top_level(amber, mock_mcp):
    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    resource_call = mock_mcp._resource_calls[-1]
    assert resource_call["uri"] == "ui://simple"


def test_uri_nested(amber, mock_mcp):
    @amber.tool(Path("nested/page.tsx"))
    def my_tool():
        pass

    resource_call = mock_mcp._resource_calls[-1]
    assert resource_call["uri"] == "ui://nested/page"


def test_sets_meta_ui(amber, mock_mcp):
    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    tool_call = mock_mcp._tool_calls[-1]
    assert "ui" in tool_call["meta"]
    assert tool_call["meta"]["ui"]["resourceUri"] == "ui://simple"


def test_preserves_existing_meta(amber, mock_mcp):
    @amber.tool(Path("simple.tsx"), meta={"custom": "value"})
    def my_tool():
        pass

    tool_call = mock_mcp._tool_calls[-1]
    assert tool_call["meta"]["custom"] == "value"
    assert "ui" in tool_call["meta"]


def test_registers_mcp_tool(amber, mock_mcp):
    @amber.tool(Path("simple.tsx"), name="my_tool", title="My Tool", description="desc")
    def my_tool():
        pass

    mock_mcp.tool.assert_called_once()
    call_kwargs = mock_mcp._tool_calls[-1]
    assert call_kwargs["name"] == "my_tool"
    assert call_kwargs["title"] == "My Tool"
    assert call_kwargs["description"] == "desc"


def test_registers_mcp_resource(amber, mock_mcp):
    @amber.tool(Path("simple.tsx"), name="my_tool", title="My Tool", description="desc")
    def my_tool():
        pass

    mock_mcp.resource.assert_called_once()
    call_kwargs = mock_mcp._resource_calls[-1]
    assert call_kwargs["uri"] == "ui://simple"
    assert call_kwargs["mime_type"] == "text/html;profile=mcp-app"


@pytest.mark.asyncio
async def test_resource_reads_js(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "simple.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "console.log('hello');" in html
    assert '<script type="module">' in html


@pytest.mark.asyncio
async def test_resource_includes_css_when_present(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    out = amber_output / "simple.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("console.log('hello');", encoding="utf-8")
    (amber_output / "simple.css").write_text("body { color: red; }", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<style>" in html
    assert "body { color: red; }" in html


@pytest.mark.asyncio
async def test_resource_omits_css_when_absent(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "simple.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<style>" not in html


@pytest.mark.asyncio
async def test_resource_uses_resolved_output(mock_mcp, views_dir, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    amber = Amber(mcp=mock_mcp, views=views_dir, output=Path("rel-out"))

    # output should have been resolved to absolute at construction time
    assert amber.output == tmp_path / "rel-out"

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    # Write the JS file at the resolved absolute path
    js_path = tmp_path / "rel-out" / "simple.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('resolved');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "console.log('resolved');" in html


@pytest.mark.asyncio
async def test_resource_raises_friendly_error_when_js_missing(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    handler = mock_mcp._resource_calls[-1]["handler"]

    with pytest.raises(FileNotFoundError, match="Has the bundler been run"):
        await handler()


@pytest.mark.asyncio
async def test_constructor_metadata_applies_to_tool_resource(mock_mcp, views_dir, tmp_path):
    amber = Amber(
        mcp=mock_mcp,
        views=views_dir,
        metadata={
            "title": "Root App",
            "description": "Shared description",
            "openGraph": {"title": "Shared OG"},
        },
    )
    object.__setattr__(amber, "output", tmp_path / "output")

    @amber.tool(Path("simple.tsx"))
    def my_tool():
        pass

    js_path = amber.output / "simple.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<title>Root App</title>" in html
    assert '<meta name="description" content="Shared description" />' in html
    assert '<meta property="og:title" content="Shared OG" />' in html


@pytest.mark.asyncio
async def test_tool_metadata_overrides_constructor_metadata_shallowly(mock_mcp, views_dir, tmp_path):
    amber = Amber(
        mcp=mock_mcp,
        views=views_dir,
        metadata={
            "description": "Shared description",
            "openGraph": {"title": "Shared OG", "description": "Shared OG description"},
        },
    )
    object.__setattr__(amber, "output", tmp_path / "output")

    @amber.tool(
        Path("simple.tsx"),
        metadata={"title": "Tool Title", "openGraph": {"title": "Tool OG"}},
    )
    def my_tool():
        pass

    js_path = amber.output / "simple.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<title>Tool Title</title>" in html
    assert '<meta name="description" content="Shared description" />' in html
    assert '<meta property="og:title" content="Tool OG" />' in html
    assert "Shared OG description" not in html


@pytest.mark.asyncio
async def test_metadata_merge_is_non_mutating(mock_mcp, views_dir, tmp_path):
    base_metadata: Metadata = {"openGraph": {"title": "Shared OG"}}
    tool_metadata: Metadata = {"openGraph": {"title": "Tool OG"}}
    amber = Amber(mcp=mock_mcp, views=views_dir, metadata=base_metadata)
    object.__setattr__(amber, "output", tmp_path / "output")

    @amber.tool(Path("simple.tsx"), metadata=tool_metadata)
    def my_tool():
        pass

    js_path = amber.output / "simple.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    await handler()

    assert base_metadata == {"openGraph": {"title": "Shared OG"}}
    assert tool_metadata == {"openGraph": {"title": "Tool OG"}}


def test_returns_original_function(amber):
    def my_tool():
        return "original"

    result = amber.tool(Path("simple.tsx"))(my_tool)
    assert result is my_tool
    assert result() == "original"


# --- Template rendering ---


def test_inlines_css():
    js = "console.log('hello');"
    css = "body { color: red; }"
    html = Amber._env.render_template(Amber._template, js=js, css=css, metadata=None)

    assert "<style>" in html
    assert css in html
    assert js in html


def test_no_css():
    js = "console.log('hello');"
    html = Amber._env.render_template(Amber._template, js=js, css="", metadata=None)

    assert "<style>" not in html
    assert js in html


def test_html_structure():
    js = "console.log('test');"
    html = Amber._env.render_template(Amber._template, js=js, css="", metadata=None)

    assert html.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8" />' in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1" />' in html
    assert '<div id="root"></div>' in html
    assert '<script type="module">' in html


def test_js_injected_in_script_tag():
    js = "const x = 42;"
    html = Amber._env.render_template(Amber._template, js=js, css="", metadata=None)

    script_start = html.index('<script type="module">')
    script_end = html.index("</script>")
    script_content = html[script_start:script_end]
    assert js in script_content
