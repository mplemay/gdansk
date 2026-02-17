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
    file_path = views_dir / "apps/simple/app.tsx"
    with pytest.raises(ValueError, match="does not exist"):
        Amber(mcp=mock_mcp, views=file_path)


def test_raises_when_views_missing(mock_mcp, tmp_path):
    missing = tmp_path / "nonexistent"
    with pytest.raises(ValueError, match="does not exist"):
        Amber(mcp=mock_mcp, views=missing)


def test_rejects_output_argument(mock_mcp, views_dir):
    with pytest.raises(TypeError, match="output"):
        Amber(mcp=mock_mcp, views=views_dir, output=Path("out.txt"))  # ty: ignore[unknown-argument]


def test_default_output(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    assert amber.output == views_dir / ".gdansk"


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
def test_no_plugins_called_when_no_paths_registered(mock_mcp, views_dir):
    called = False

    class _TestPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)
            nonlocal called
            called = True

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_TestPlugin()])
    with patch("gdansk.core.bundle") as mock_bundle, amber():
        pass

    assert called is False
    mock_bundle.assert_not_called()


@pytest.mark.usefixtures("views_dir")
def test_blocking_calls_bundle(amber):
    amber._paths.add(Path("simple/app.tsx"))

    called = False

    async def _fake_bundle(**_kwargs: object):
        nonlocal called
        called = True

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert called


@pytest.mark.usefixtures("views_dir")
def test_plugins_run_after_bundle(mock_mcp, views_dir):
    calls: list[str] = []

    class _TestPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)
            calls.append("plugin")

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_TestPlugin()])
    amber._paths.add(Path("simple/app.tsx"))

    async def _fake_bundle(**_kwargs: object):
        calls.append("bundle")

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert calls == ["bundle", "plugin"]


@pytest.mark.usefixtures("views_dir")
def test_non_blocking_runs_in_background_thread(amber):
    amber._paths.add(Path("simple/app.tsx"))
    threads_during: list[list[threading.Thread]] = []

    async def _fake_bundle(**_kwargs: object):
        pass

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=False):
        threads_during.append(
            [t for t in threading.enumerate() if t.daemon and t.is_alive()],
        )

    assert len(threads_during[0]) >= 1


@pytest.mark.usefixtures("views_dir")
def test_dev_plugin_watcher_is_cancelled_on_exit(mock_mcp, views_dir):
    watcher_started = threading.Event()
    watcher_cancelled = threading.Event()
    bundle_cancelled = threading.Event()

    class _DevPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)
            watcher_started.set()
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                watcher_cancelled.set()
                raise

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_DevPlugin()])
    amber._paths.add(Path("simple/app.tsx"))

    async def _slow_bundle(**_kwargs: object):
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            bundle_cancelled.set()
            raise

    with patch("gdansk.core.bundle", _slow_bundle), amber(blocking=False, dev=True):
        assert watcher_started.wait(timeout=5)

    assert watcher_cancelled.wait(timeout=5)
    assert bundle_cancelled.wait(timeout=5)


@pytest.mark.usefixtures("views_dir")
def test_passes_dev_flag(amber):
    amber._paths.add(Path("simple/app.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=True):
        pass

    assert captured[-1]["dev"] is True

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=False):
        pass

    assert captured[-1]["dev"] is False


@pytest.mark.usefixtures("views_dir")
def test_plugin_errors_propagate_in_blocking_mode(mock_mcp, views_dir):
    class _FailingPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)
            msg = "plugin boom"
            raise RuntimeError(msg)

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_FailingPlugin()])
    amber._paths.add(Path("simple/app.tsx"))

    async def _fake_bundle(**_kwargs: object):
        return

    with (
        patch("gdansk.core.bundle", _fake_bundle),
        pytest.raises(RuntimeError, match="plugin boom"),
        amber(blocking=True),
    ):
        pass


@pytest.mark.usefixtures("views_dir")
def test_default_minify_true_when_not_dev(amber):
    amber._paths.add(Path("simple/app.tsx"))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=False):
        pass

    assert captured[-1]["minify"] is True


@pytest.mark.usefixtures("views_dir")
def test_default_minify_false_when_dev(amber):
    amber._paths.add(Path("simple/app.tsx"))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=True):
        pass

    assert captured[-1]["minify"] is False


@pytest.mark.usefixtures("views_dir")
def test_explicit_minify_true_overrides_dev_default(amber):
    amber._paths.add(Path("simple/app.tsx"))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=True, minify=True):
        pass

    assert captured[-1]["minify"] is True


@pytest.mark.usefixtures("views_dir")
def test_explicit_minify_false_overrides_prod_default(amber):
    amber._paths.add(Path("simple/app.tsx"))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True, dev=False, minify=False):
        pass

    assert captured[-1]["minify"] is False


def test_passes_views_dot_gdansk_as_output(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    amber._paths.add(Path("simple/app.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["output"] == views_dir / ".gdansk"


def test_passes_views_as_cwd(amber, views_dir):
    amber._paths.add(Path("simple/app.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["cwd"] == views_dir


@pytest.mark.usefixtures("views_dir")
def test_passes_registered_paths(amber):
    amber._paths.add(Path("simple/app.tsx"))
    amber._paths.add(Path("nested/page/app.tsx"))

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), amber(blocking=True):
        pass

    assert captured[-1]["paths"] == {Path("apps/simple/app.tsx"), Path("apps/nested/page/app.tsx")}


@pytest.mark.usefixtures("views_dir")
def test_cancels_task_on_exit(amber):
    amber._paths.add(Path("simple/app.tsx"))

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
    amber._paths.add(Path("simple/app.tsx"))

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
    decorator = amber.tool(Path("simple/app.tsx"))
    assert callable(decorator)


def test_rejects_non_apps_path(amber):
    with pytest.raises(ValueError, match=r"must match \*\*/app\.tsx or \*\*/app\.jsx"):
        amber.tool(Path("simple.tsx"))


def test_rejects_apps_prefixed_path(amber):
    with pytest.raises(ValueError, match="must not start with apps/"):
        amber.tool(Path("apps/simple/app.tsx"))


def test_rejects_non_app_entry_filename(mock_mcp, views_dir):
    wrong_entry = views_dir / "apps" / "wrong" / "page.tsx"
    wrong_entry.parent.mkdir(parents=True, exist_ok=True)
    wrong_entry.write_text("export const page = 1;\n", encoding="utf-8")

    amber = Amber(mcp=mock_mcp, views=views_dir)
    with pytest.raises(ValueError, match=r"must match \*\*/app\.tsx or \*\*/app\.jsx"):
        amber.tool(Path("wrong/page.tsx"))


def test_rejects_absolute_ui_path(amber, views_dir):
    with pytest.raises(ValueError, match="must be a relative path"):
        amber.tool(views_dir / "apps/simple/app.tsx")


def test_rejects_traversal_segments(amber):
    with pytest.raises(ValueError, match="must not contain traversal segments"):
        amber.tool(Path("simple/../simple/app.tsx"))


def test_accepts_jsx(mock_mcp, views_dir):
    jsx_path = views_dir / "apps" / "jsx" / "app.jsx"
    jsx_path.parent.mkdir(parents=True, exist_ok=True)
    jsx_path.write_text("export const app = 1;\n", encoding="utf-8")

    amber = Amber(mcp=mock_mcp, views=views_dir)
    decorator = amber.tool(Path("jsx/app.jsx"))
    assert callable(decorator)


def test_raises_when_file_not_found(amber):
    with pytest.raises(FileNotFoundError, match="was not found"):
        amber.tool(Path("missing/app.tsx"))


def test_adds_path_to_paths(amber):
    assert Path("simple/app.tsx") not in amber.paths

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    assert Path("simple/app.tsx") in amber.paths


def test_uri_top_level(amber, mock_mcp):
    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    resource_call = mock_mcp._resource_calls[-1]
    assert resource_call["uri"] == "ui://simple"


def test_uri_nested(amber, mock_mcp):
    @amber.tool(Path("nested/page/app.tsx"))
    def my_tool():
        pass

    resource_call = mock_mcp._resource_calls[-1]
    assert resource_call["uri"] == "ui://nested/page"


def test_sets_meta_ui(amber, mock_mcp):
    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    tool_call = mock_mcp._tool_calls[-1]
    assert "ui" in tool_call["meta"]
    assert tool_call["meta"]["ui"]["resourceUri"] == "ui://simple"


def test_preserves_existing_meta(amber, mock_mcp):
    @amber.tool(Path("simple/app.tsx"), meta={"custom": "value"})
    def my_tool():
        pass

    tool_call = mock_mcp._tool_calls[-1]
    assert tool_call["meta"]["custom"] == "value"
    assert "ui" in tool_call["meta"]


def test_registers_mcp_tool(amber, mock_mcp):
    @amber.tool(Path("simple/app.tsx"), name="my_tool", title="My Tool", description="desc")
    def my_tool():
        pass

    mock_mcp.tool.assert_called_once()
    call_kwargs = mock_mcp._tool_calls[-1]
    assert call_kwargs["name"] == "my_tool"
    assert call_kwargs["title"] == "My Tool"
    assert call_kwargs["description"] == "desc"


def test_registers_mcp_resource(amber, mock_mcp):
    @amber.tool(Path("simple/app.tsx"), name="my_tool", title="My Tool", description="desc")
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

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "apps/simple/app.js"
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

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    out = amber_output / "apps/simple/app.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("console.log('hello');", encoding="utf-8")
    (amber_output / "apps/simple/app.css").write_text("body { color: red; }", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<style>" in html
    assert "body { color: red; }" in html


@pytest.mark.asyncio
async def test_resource_omits_css_when_absent(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "apps/simple/app.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<style>" not in html


@pytest.mark.asyncio
async def test_resource_uses_views_dot_gdansk_output(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    assert amber.output == views_dir / ".gdansk"

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = views_dir / ".gdansk" / "apps/simple/app.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('resolved');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "console.log('resolved');" in html


@pytest.mark.asyncio
async def test_resource_raises_friendly_error_when_js_missing(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple/app.tsx"))
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

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber.output / "apps/simple/app.js"
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
        Path("simple/app.tsx"),
        metadata={"title": "Tool Title", "openGraph": {"title": "Tool OG"}},
    )
    def my_tool():
        pass

    js_path = amber.output / "apps/simple/app.js"
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

    @amber.tool(Path("simple/app.tsx"), metadata=tool_metadata)
    def my_tool():
        pass

    js_path = amber.output / "apps/simple/app.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    await handler()

    assert base_metadata == {"openGraph": {"title": "Shared OG"}}
    assert tool_metadata == {"openGraph": {"title": "Tool OG"}}


def test_returns_original_function(amber):
    def my_tool():
        return "original"

    result = amber.tool(Path("simple/app.tsx"))(my_tool)
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
