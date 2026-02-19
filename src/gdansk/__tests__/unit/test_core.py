from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from gdansk.core import Amber, View
from gdansk.render import ENV

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


def test_amber_defaults_ssr_false(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    assert amber.ssr is False


def test_paths_empty_initially(amber):
    assert amber.paths == frozenset()


def test_frozen_dataclass(amber):
    with pytest.raises(dataclasses.FrozenInstanceError):
        amber.mcp = None


# --- __call__ app factory ---


@contextmanager
def _lifespan(app):
    loop = asyncio.new_event_loop()
    context = app.router.lifespan_context(app)
    entered = False
    try:
        loop.run_until_complete(context.__aenter__())
        entered = True
        yield
    finally:
        if entered:
            loop.run_until_complete(context.__aexit__(None, None, None))
        loop.close()


def test_noop_when_no_paths_registered(amber):
    app = amber()
    assert app is amber.mcp.streamable_http_app.return_value


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
    with patch("gdansk.core.bundle") as mock_bundle:
        amber(dev=True)
    assert called is False
    mock_bundle.assert_not_called()


@pytest.mark.usefixtures("views_dir")
def test_dev_false_blocks_until_bundle_done(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    called = False

    async def _fake_bundle(**_kwargs: object):
        nonlocal called
        called = True

    with patch("gdansk.core.bundle", _fake_bundle):
        app = amber(dev=False)
        with _lifespan(app):
            assert called is True


@pytest.mark.usefixtures("views_dir")
def test_plugins_run_after_bundle_in_prod(mock_mcp, views_dir):
    calls: list[str] = []

    class _TestPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)
            calls.append("plugin")

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_TestPlugin()])
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))

    async def _fake_bundle(**_kwargs: object):
        calls.append("bundle")

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(amber(dev=False)):
        pass

    assert calls == ["bundle", "plugin"]


@pytest.mark.usefixtures("views_dir")
def test_dev_true_starts_background_runner(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    started = threading.Event()

    async def _slow_bundle(**_kwargs: object):
        started.set()
        await asyncio.sleep(999)

    with patch("gdansk.core.bundle", _slow_bundle):
        app = amber(dev=True)
        with _lifespan(app):
            assert started.wait(timeout=5)
            thread_count = len([t for t in threading.enumerate() if t.daemon and t.is_alive()])
            assert thread_count >= 1


@pytest.mark.usefixtures("views_dir")
def test_passes_dev_flag_and_derived_minify(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle):
        with _lifespan(amber(dev=True)):
            pass
        with _lifespan(amber(dev=False)):
            pass

    assert captured[0]["dev"] is True
    assert captured[0]["minify"] is False
    assert captured[1]["dev"] is False
    assert captured[1]["minify"] is True


@pytest.mark.usefixtures("views_dir")
def test_plugin_errors_propagate_in_prod(mock_mcp, views_dir):
    class _FailingPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)
            msg = "plugin boom"
            raise RuntimeError(msg)

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_FailingPlugin()])
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))

    async def _fake_bundle(**_kwargs: object):
        return

    with (
        patch("gdansk.core.bundle", _fake_bundle),
        pytest.raises(RuntimeError, match="plugin boom"),
        _lifespan(
            amber(dev=False),
        ),
    ):
        pass


def test_passes_views_dot_gdansk_as_output(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(amber(dev=False)):
        pass

    assert captured[-1]["output"] == views_dir / ".gdansk"


def test_passes_views_as_cwd(amber, views_dir):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(amber(dev=False)):
        pass

    assert captured[-1]["cwd"] == views_dir


@pytest.mark.usefixtures("views_dir")
def test_passes_view_specs_for_amber_ui_entries(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(amber(dev=False)):
        pass

    assert captured[-1]["views"] == [View(path=Path("apps/simple/app.tsx"), app=True, ssr=False)]


@pytest.mark.usefixtures("views_dir")
def test_passes_registered_paths(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    amber._apps.add(View(path=Path("nested/page/app.tsx"), app=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(amber(dev=False)):
        pass

    assert {(view.path, view.app, view.ssr) for view in captured[-1]["views"]} == {
        (Path("apps/simple/app.tsx"), True, False),
        (Path("apps/nested/page/app.tsx"), True, False),
    }


@pytest.mark.usefixtures("views_dir")
def test_run_build_pipeline_invokes_server_bundle_only_for_ssr_paths(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def tool_a():
        pass

    @amber.tool(Path("nested/page/app.tsx"), ssr=True)
    def tool_b():
        pass

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(amber(dev=False)):
        pass

    assert len(captured) == 1
    assert captured[0]["output"] == views_dir / ".gdansk"
    assert {(view.path, view.app, view.ssr) for view in captured[0]["views"]} == {
        (Path("apps/simple/app.tsx"), True, False),
        (Path("apps/nested/page/app.tsx"), True, True),
    }


@pytest.mark.usefixtures("views_dir")
def test_plugins_watch_started_and_cancelled_on_shutdown(mock_mcp, views_dir):
    watcher_started = threading.Event()
    watcher_cancelled = threading.Event()
    bundle_cancelled = threading.Event()

    class _DevPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output)
            watcher_started.set()
            try:
                await stop_event.wait()
            except asyncio.CancelledError:
                watcher_cancelled.set()
                raise

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_DevPlugin()])
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))

    async def _slow_bundle(**_kwargs: object):
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            bundle_cancelled.set()
            raise

    with patch("gdansk.core.bundle", _slow_bundle), _lifespan(amber(dev=True)):
        assert watcher_started.wait(timeout=5)

    assert bundle_cancelled.wait(timeout=5)
    assert watcher_cancelled.wait(timeout=5)


@pytest.mark.usefixtures("views_dir")
def test_dev_watch_error_is_logged(mock_mcp, views_dir):
    class _FailingWatchPlugin:
        async def build(self, *, views: Path, output: Path) -> None:
            _ = (views, output)

        async def watch(self, *, views: Path, output: Path, stop_event: asyncio.Event) -> None:
            _ = (views, output, stop_event)
            msg = "watch failed"
            raise RuntimeError(msg)

    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[_FailingWatchPlugin()])
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))

    async def _slow_bundle(**_kwargs: object):
        await asyncio.sleep(999)

    with (
        patch("gdansk.core.bundle", _slow_bundle),
        patch("gdansk.core.logger.exception") as mock_log,
        _lifespan(amber(dev=True)),
    ):
        deadline = time.monotonic() + 5
        while mock_log.call_count == 0 and time.monotonic() < deadline:
            time.sleep(0.05)

    assert mock_log.call_count >= 1


@pytest.mark.usefixtures("views_dir")
def test_closes_loop_on_shutdown(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))
    loops: list[asyncio.AbstractEventLoop] = []
    original_new_event_loop = asyncio.new_event_loop

    def _capture_loop():
        loop = original_new_event_loop()
        loops.append(loop)
        return loop

    async def _fake_bundle(**_kwargs: object):
        await asyncio.sleep(999)

    with (
        patch("gdansk.core.asyncio.new_event_loop", _capture_loop),
        patch(
            "gdansk.core.bundle",
            _fake_bundle,
        ),
        _lifespan(amber(dev=True)),
    ):
        pass

    assert len(loops) >= 1
    assert all(loop.is_closed() for loop in loops)


@pytest.mark.usefixtures("views_dir")
def test_repeated_startup_shutdown_is_idempotent(amber):
    amber._apps.add(View(path=Path("simple/app.tsx"), app=True, ssr=False))

    async def _fake_bundle(**_kwargs: object):
        await asyncio.sleep(0)

    with patch("gdansk.core.bundle", _fake_bundle):
        app = amber(dev=True)
        with _lifespan(app):
            pass
        with _lifespan(app):
            pass


def test_with_amber_context_manager_raises_type_error(amber):
    with pytest.raises(TypeError), amber():
        pass


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


def test_tool_ssr_none_inherits_amber_value(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    _ = my_tool
    assert View(path=Path("simple/app.tsx"), app=True, ssr=True) in amber._apps


def test_tool_ssr_true_overrides_amber_false(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=False)

    @amber.tool(Path("simple/app.tsx"), ssr=True)
    def my_tool():
        pass

    _ = my_tool
    assert View(path=Path("simple/app.tsx"), app=True, ssr=True) in amber._apps


def test_tool_ssr_false_overrides_amber_true(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)

    @amber.tool(Path("simple/app.tsx"), ssr=False)
    def my_tool():
        pass

    _ = my_tool
    assert View(path=Path("simple/app.tsx"), app=True, ssr=False) in amber._apps


def test_tool_reregistration_overwrites_ssr_for_same_path(mock_mcp, views_dir):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=False)

    @amber.tool(Path("simple/app.tsx"), ssr=False)
    def first_tool():
        pass

    @amber.tool(Path("simple/app.tsx"), ssr=True)
    def second_tool():
        pass

    _ = (first_tool, second_tool)
    assert View(path=Path("simple/app.tsx"), app=True, ssr=True) in amber._apps
    assert sum(1 for view in amber._apps if view.path == Path("simple/app.tsx")) == 1


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

    js_path = amber_output / "simple/client.js"
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

    out = amber_output / "simple/client.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("console.log('hello');", encoding="utf-8")
    (amber_output / "simple/client.css").write_text("body { color: red; }", encoding="utf-8")

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

    js_path = amber_output / "simple/client.js"
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

    js_path = views_dir / ".gdansk" / "simple/client.js"
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
async def test_resource_injects_ssr_html_when_effective_ssr_true(mock_mcp, views_dir, tmp_path):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")
    server_js_path = amber_output / "simple/server.js"
    server_js_path.parent.mkdir(parents=True, exist_ok=True)
    server_js_path.write_text('Deno.core.ops.op_gdansk_set_ssr_html("<p>server</p>");', encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "<p>server</p>"
        html = await handler()

    assert '<div id="root"><p>server</p></div>' in html


@pytest.mark.asyncio
async def test_resource_skips_runtime_and_ssr_html_when_effective_ssr_false(amber, mock_mcp, tmp_path):
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        html = await handler()

    assert '<div id="root"></div>' in html
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_resource_raises_when_ssr_bundle_missing(mock_mcp, views_dir, tmp_path):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with pytest.raises(FileNotFoundError, match="SSR bundled output"):
        await handler()


@pytest.mark.asyncio
async def test_resource_propagates_runtime_error_fail_fast(mock_mcp, views_dir, tmp_path):
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)
    amber_output = tmp_path / "output"
    object.__setattr__(amber, "output", amber_output)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        pass

    js_path = amber_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")
    server_js_path = amber_output / "simple/server.js"
    server_js_path.parent.mkdir(parents=True, exist_ok=True)
    server_js_path.write_text('Deno.core.ops.op_gdansk_set_ssr_html("<p>server</p>");', encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
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

    js_path = amber.output / "simple/client.js"
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

    js_path = amber.output / "simple/client.js"
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

    js_path = amber.output / "simple/client.js"
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
    html = ENV.render_template(Amber._template, js=js, css=css, metadata=None)

    assert "<style>" in html
    assert css in html
    assert js in html


def test_no_css():
    js = "console.log('hello');"
    html = ENV.render_template(Amber._template, js=js, css="", metadata=None)

    assert "<style>" not in html
    assert js in html


def test_html_structure():
    js = "console.log('test');"
    html = ENV.render_template(Amber._template, js=js, css="", metadata=None)

    assert html.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8" />' in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1" />' in html
    assert '<div id="root"></div>' in html
    assert '<script type="module">' in html


def test_js_injected_in_script_tag():
    js = "const x = 42;"
    html = ENV.render_template(Amber._template, js=js, css="", metadata=None)

    script_start = html.index('<script type="module">')
    script_end = html.index("</script>")
    script_content = html[script_start:script_end]
    assert js in script_content


def test_ssr_html_rendered_in_root():
    js = "const x = 42;"
    html = ENV.render_template(Amber._template, js=js, css="", ssr_html="<span>server</span>", metadata=None)

    assert '<div id="root"><span>server</span></div>' in html
