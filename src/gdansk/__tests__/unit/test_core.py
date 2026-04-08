from __future__ import annotations

import asyncio
import dataclasses
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from gdansk_bundler import Plugin

from gdansk import LightningCSS, VitePlugin
from gdansk.core import Page, Ship
from gdansk.render import ENV

if TYPE_CHECKING:
    from gdansk.metadata import Metadata

# --- __post_init__ + paths property ---


def test_valid_construction(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    assert ship.mcp is mock_mcp
    assert ship.views == pages_dir


def test_ship_views_accepts_str(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=os.fspath(pages_dir))
    assert isinstance(ship.views, Path)
    assert ship.views == pages_dir


def test_ship_views_accepts_pure_posix_path(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=PurePosixPath(pages_dir.as_posix()))
    assert isinstance(ship.views, Path)
    assert ship.views == pages_dir


def test_raises_when_pages_not_directory(mock_mcp, pages_dir):
    file_path = pages_dir / "widgets/simple/widget.tsx"
    with pytest.raises(ValueError, match="does not exist"):
        Ship(mcp=mock_mcp, views=file_path)


def test_raises_when_pages_missing(mock_mcp, tmp_path):
    missing = tmp_path / "nonexistent"
    with pytest.raises(ValueError, match="does not exist"):
        Ship(mcp=mock_mcp, views=missing)


def test_rejects_output_argument(mock_mcp, pages_dir):
    with pytest.raises(TypeError, match="output"):
        Ship(mcp=mock_mcp, views=pages_dir, output=Path("out.txt"))  # ty: ignore[unknown-argument]


def test_rejects_pages_argument(mock_mcp, pages_dir):
    with pytest.raises(TypeError, match="pages"):
        Ship(mcp=mock_mcp, views=pages_dir, pages=pages_dir)  # ty: ignore[unknown-argument]


def test_rejects_lifecycle_plugins_argument(mock_mcp, pages_dir):
    with pytest.raises(TypeError, match="lifecycle_plugins"):
        Ship(
            mcp=mock_mcp,
            views=pages_dir,
            lifecycle_plugins=[],  # ty: ignore[unknown-argument]
        )


def test_rejects_js_plugins_argument(mock_mcp, pages_dir):
    with pytest.raises(TypeError, match="js_plugins"):
        Ship(
            mcp=mock_mcp,
            views=pages_dir,
            js_plugins=[],  # ty: ignore[unknown-argument]
        )


def test_rejects_unknown_plugin_objects(mock_mcp, pages_dir):
    class _IdOnlyPlugin:
        id = "not-allowed"

    with pytest.raises(TypeError, match="gdansk_bundler\\.Plugin"):
        Ship(
            mcp=mock_mcp,
            views=pages_dir,
            plugins=[_IdOnlyPlugin()],  # ty: ignore[invalid-argument-type]
        )


def test_accepts_generic_bundler_plugins(mock_mcp, pages_dir):
    class _CustomPlugin(Plugin):
        def __init__(self) -> None:
            super().__init__(id="custom")

    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[_CustomPlugin()],
    )

    assert ship.plugins is not None
    assert isinstance(ship.plugins[0], Plugin)
    assert ship.plugins[0].id == "custom"


def test_default_output(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    assert ship.output == pages_dir / ".gdansk"


def test_ship_defaults_ssr_false(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    assert ship.ssr is False


def test_ship_defaults_cache_html_true(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    assert ship.cache_html is True


def test_registered_views_empty_initially(ship):
    assert ship._widgets == set()


def test_frozen_dataclass(ship):
    with pytest.raises(dataclasses.FrozenInstanceError):
        ship.mcp = None


# --- __call__ app factory ---


@contextmanager
def _lifespan(app, *, background: bool = False):
    loop = asyncio.new_event_loop()
    context = app.router.lifespan_context(app)
    entered = False
    loop_thread: threading.Thread | None = None
    try:
        if background:
            loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
            loop_thread.start()
            asyncio.run_coroutine_threadsafe(context.__aenter__(), loop).result()
        else:
            loop.run_until_complete(context.__aenter__())
        entered = True
        yield
    finally:
        if entered:
            if background:
                asyncio.run_coroutine_threadsafe(context.__aexit__(None, None, None), loop).result()
            else:
                loop.run_until_complete(context.__aexit__(None, None, None))
        if loop_thread is not None:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
        loop.close()


def test_noop_when_no_paths_registered(ship):
    app = ship()
    assert app is ship.mcp.streamable_http_app.return_value


@pytest.mark.usefixtures("pages_dir")
def test_no_plugins_called_when_no_paths_registered(mock_mcp, pages_dir):
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier="plugins/append-comment.mjs")],
    )
    with patch("gdansk.core.bundle") as mock_bundle:
        ship(dev=True)
    mock_bundle.assert_not_called()


@pytest.mark.usefixtures("pages_dir")
def test_dev_false_blocks_until_bundle_done(ship):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    called = False

    async def _fake_bundle(**_kwargs: object):
        nonlocal called
        called = True

    with patch("gdansk.core.bundle", _fake_bundle):
        app = ship(dev=False)
        with _lifespan(app):
            assert called is True


@pytest.mark.usefixtures("pages_dir")
def test_vite_plugins_are_forwarded_without_serialization_in_prod(mock_mcp, pages_dir):
    plugins = [VitePlugin(specifier="plugins/append-comment.mjs", options={"comment": "prod"})]
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=plugins,
    )
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with (
        patch("gdansk.core.bundle", _fake_bundle),
        _lifespan(ship(dev=False)),
    ):
        pass

    assert captured[-1]["plugins"] is plugins


@pytest.mark.usefixtures("pages_dir")
def test_dev_true_starts_background_task(ship):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    started = threading.Event()
    created_tasks: list[asyncio.Task[None]] = []
    original_create_task = asyncio.create_task

    async def _slow_bundle(**_kwargs: object):
        started.set()
        ready = _kwargs.get("_ready")
        if isinstance(ready, asyncio.Event):
            ready.set()
        await asyncio.sleep(999)

    def _capture_create_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        return task

    with (
        patch("gdansk.core.bundle", _slow_bundle),
        patch("gdansk.core.asyncio.create_task", side_effect=_capture_create_task),
    ):
        app = ship(dev=True)
        with _lifespan(app, background=True):
            assert started.wait(timeout=5)
            assert len(created_tasks) == 1
            assert created_tasks[0].done() is False


@pytest.mark.usefixtures("pages_dir")
def test_passes_dev_flag_and_derived_minify(ship):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle):
        with _lifespan(ship(dev=True), background=True):
            pass
        with _lifespan(ship(dev=False)):
            pass

    assert captured[0]["dev"] is True
    assert captured[0]["minify"] is False
    assert captured[1]["dev"] is False
    assert captured[1]["minify"] is True


def test_default_bundler_plugins_use_public_bundle(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["pages"] == [Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False)]
    assert captured[-1]["plugins"] is None


def test_explicit_lightningcss_plugin_is_forwarded_to_bundle_payload(mock_mcp, pages_dir):
    plugins = [LightningCSS()]
    ship = Ship(mcp=mock_mcp, views=pages_dir, plugins=plugins)
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["plugins"] is plugins


def test_empty_bundler_plugin_list_is_forwarded(mock_mcp, pages_dir):
    plugins: list[LightningCSS] = []
    ship = Ship(mcp=mock_mcp, views=pages_dir, plugins=plugins)
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["plugins"] is plugins


def test_vite_only_plugins_are_forwarded_without_serialization(mock_mcp, pages_dir):
    plugins = [VitePlugin(specifier="plugins/append-comment.mjs")]
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=plugins,
    )
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["plugins"] is plugins


def test_mixed_plugins_are_forwarded_without_serialization(mock_mcp, pages_dir):
    plugins = [LightningCSS(), VitePlugin(specifier="plugins/append-comment.mjs")]
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=plugins,
    )
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["plugins"] is plugins


@pytest.mark.usefixtures("pages_dir")
def test_plugin_errors_propagate_in_prod(mock_mcp, pages_dir):
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier="plugins/append-comment.mjs")],
    )
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))

    async def _failing_bundle(**_kwargs: object):
        msg = "plugin boom"
        raise RuntimeError(msg)

    with (
        patch("gdansk.core.bundle", _failing_bundle),
        pytest.raises(RuntimeError, match="plugin boom"),
        _lifespan(
            ship(dev=False),
        ),
    ):
        pass


def test_passes_views_dot_gdansk_as_output(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["output"] == pages_dir / ".gdansk"


def test_passes_views_as_cwd(ship, pages_dir):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["cwd"] == pages_dir


@pytest.mark.usefixtures("pages_dir")
def test_passes_view_specs_for_ship_ui_entries(ship):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert captured[-1]["pages"] == [Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False)]


@pytest.mark.usefixtures("pages_dir")
def test_passes_registered_paths(ship):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))
    ship._widgets.add(Page(path=Path("widgets/nested/page/widget.tsx"), is_widget=True, ssr=False))
    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert {(view.path, view.is_widget, view.ssr) for view in captured[-1]["pages"]} == {
        (Path("widgets/simple/widget.tsx"), True, False),
        (Path("widgets/nested/page/widget.tsx"), True, False),
    }


@pytest.mark.usefixtures("pages_dir")
def test_run_build_pipeline_invokes_server_bundle_only_for_ssr_paths(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)

    @ship.tool(Path("simple/widget.tsx"))
    def tool_a():
        pass

    @ship.tool(Path("nested/page/widget.tsx"), ssr=True)
    def tool_b():
        pass

    captured: list[dict] = []

    async def _fake_bundle(**kwargs: object):
        captured.append(kwargs)

    with patch("gdansk.core.bundle", _fake_bundle), _lifespan(ship(dev=False)):
        pass

    assert len(captured) == 1
    assert captured[0]["output"] == pages_dir / ".gdansk"
    assert {(view.path, view.is_widget, view.ssr) for view in captured[0]["pages"]} == {
        (Path("widgets/simple/widget.tsx"), True, False),
        (Path("widgets/nested/page/widget.tsx"), True, True),
    }


@pytest.mark.usefixtures("pages_dir")
def test_dev_vite_bundle_task_cancelled_on_shutdown(mock_mcp, pages_dir):
    bundle_cancelled = threading.Event()
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier="plugins/append-comment.mjs")],
    )
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))

    async def _slow_bundle(**_kwargs: object):
        ready = _kwargs.get("_ready")
        if isinstance(ready, asyncio.Event):
            ready.set()
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            bundle_cancelled.set()
            raise

    with (
        patch("gdansk.core.bundle", _slow_bundle),
        _lifespan(
            ship(dev=True),
            background=True,
        ),
    ):
        time.sleep(0.1)

    assert bundle_cancelled.wait(timeout=5)


@pytest.mark.usefixtures("pages_dir")
def test_dev_vite_bundle_error_is_logged(mock_mcp, pages_dir):
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier="plugins/append-comment.mjs")],
    )
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))

    async def _failing_bundle(**_kwargs: object):
        msg = "watch failed"
        raise RuntimeError(msg)

    with (
        patch("gdansk.core.bundle", _failing_bundle),
        patch("gdansk.core.logger.exception") as mock_log,
        _lifespan(ship(dev=True), background=True),
    ):
        deadline = time.monotonic() + 5
        while mock_log.call_count == 0 and time.monotonic() < deadline:
            time.sleep(0.05)

    assert mock_log.call_count >= 1


@pytest.mark.usefixtures("pages_dir")
def test_repeated_startup_shutdown_is_idempotent(ship):
    ship._widgets.add(Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False))

    async def _fake_bundle(**_kwargs: object):
        await asyncio.sleep(0)

    with patch("gdansk.core.bundle", _fake_bundle):
        app = ship(dev=True)
        with _lifespan(app, background=True):
            pass
        with _lifespan(app, background=True):
            pass


def test_with_ship_context_manager_raises_type_error(ship):
    with pytest.raises(TypeError), ship():
        pass


# --- tool() decorator ---


def test_rejects_non_tsx_jsx(ship):
    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        ship.tool(Path("invalid.ts"))

    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        ship.tool(Path("page.vue"))


def test_accepts_tsx(ship):
    decorator = ship.tool(Path("simple/widget.tsx"))
    assert callable(decorator)


def test_accepts_str_page(ship):
    decorator = ship.tool("simple/widget.tsx")
    assert callable(decorator)


def test_accepts_pathlike_page(ship):
    decorator = ship.tool(PurePosixPath("simple/widget.tsx"))
    assert callable(decorator)


def test_accepts_directory_and_prefers_page_tsx(mock_mcp, pages_dir):
    preferred_path = pages_dir / "widgets" / "preferred"
    preferred_path.mkdir(parents=True, exist_ok=True)
    (preferred_path / "widget.tsx").write_text("export const tsx = 1;\n", encoding="utf-8")
    (preferred_path / "widget.jsx").write_text("export const jsx = 1;\n", encoding="utf-8")
    ship = Ship(mcp=mock_mcp, views=pages_dir)

    decorator = ship.tool(Path("preferred"))

    assert callable(decorator)
    assert Page(path=Path("widgets/preferred/widget.tsx"), is_widget=True, ssr=False) in ship._widgets


def test_accepts_directory_with_page_jsx_fallback(mock_mcp, pages_dir):
    jsx_only_path = pages_dir / "widgets" / "jsx-only"
    jsx_only_path.mkdir(parents=True, exist_ok=True)
    (jsx_only_path / "widget.jsx").write_text("export const jsx = 1;\n", encoding="utf-8")
    ship = Ship(mcp=mock_mcp, views=pages_dir)

    decorator = ship.tool(Path("jsx-only"))

    assert callable(decorator)
    assert Page(path=Path("widgets/jsx-only/widget.jsx"), is_widget=True, ssr=False) in ship._widgets


def test_rejects_non_widget_path(ship):
    with pytest.raises(ValueError, match=r"must match \*\*/widget\.tsx or \*\*/widget\.jsx"):
        ship.tool(Path("simple.tsx"))


def test_rejects_widgets_prefixed_path(ship):
    with pytest.raises(ValueError, match="must not start with widgets/"):
        ship.tool(Path("widgets/simple/widget.tsx"))


def test_rejects_non_widget_entry_filename(mock_mcp, pages_dir):
    wrong_entry = pages_dir / "widgets" / "wrong" / "app.tsx"
    wrong_entry.parent.mkdir(parents=True, exist_ok=True)
    wrong_entry.write_text("export const page = 1;\n", encoding="utf-8")

    ship = Ship(mcp=mock_mcp, views=pages_dir)
    with pytest.raises(ValueError, match=r"must match \*\*/widget\.tsx or \*\*/widget\.jsx"):
        ship.tool(Path("wrong/app.tsx"))


def test_rejects_absolute_page_path(ship, pages_dir):
    with pytest.raises(ValueError, match="must be a relative path"):
        ship.tool(pages_dir / "widgets/simple/widget.tsx")


def test_rejects_traversal_segments(ship):
    with pytest.raises(ValueError, match="must not contain traversal segments"):
        ship.tool(Path("simple/../simple/widget.tsx"))


def test_accepts_jsx(mock_mcp, pages_dir):
    jsx_path = pages_dir / "widgets" / "jsx" / "widget.jsx"
    jsx_path.parent.mkdir(parents=True, exist_ok=True)
    jsx_path.write_text("export const app = 1;\n", encoding="utf-8")

    ship = Ship(mcp=mock_mcp, views=pages_dir)
    decorator = ship.tool(Path("jsx/widget.jsx"))
    assert callable(decorator)


def test_raises_when_file_not_found(ship):
    with pytest.raises(FileNotFoundError, match="was not found"):
        ship.tool(Path("missing/widget.tsx"))


def test_raises_when_directory_missing_page_files(ship):
    with pytest.raises(FileNotFoundError, match="Expected one of"):
        ship.tool(Path("missing"))


def test_rejects_page_keyword_argument(ship):
    with pytest.raises(TypeError, match="page"):
        ship.tool(page=Path("simple/widget.tsx"))


def test_adds_bundle_path_to_registered_views(ship):
    assert Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False) not in ship._widgets

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    assert Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False) in ship._widgets


def test_tool_ssr_none_inherits_ship_value(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    _ = my_tool
    assert Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=True) in ship._widgets


def test_tool_ssr_true_overrides_ship_false(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=False)

    @ship.tool(Path("simple/widget.tsx"), ssr=True)
    def my_tool():
        pass

    _ = my_tool
    assert Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=True) in ship._widgets


def test_tool_ssr_false_overrides_ship_true(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True)

    @ship.tool(Path("simple/widget.tsx"), ssr=False)
    def my_tool():
        pass

    _ = my_tool
    assert Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=False) in ship._widgets


def test_tool_reregistration_overwrites_ssr_for_same_path(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=False)

    @ship.tool(Path("simple/widget.tsx"), ssr=False)
    def first_tool():
        pass

    @ship.tool(Path("simple/widget.tsx"), ssr=True)
    def second_tool():
        pass

    _ = (first_tool, second_tool)
    assert Page(path=Path("widgets/simple/widget.tsx"), is_widget=True, ssr=True) in ship._widgets
    assert sum(1 for view in ship._widgets if view.path == Path("widgets/simple/widget.tsx")) == 1


def test_uri_top_level(ship, mock_mcp):
    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    resource_call = mock_mcp._resource_calls[-1]
    assert resource_call["uri"] == "ui://simple"


def test_uri_nested(ship, mock_mcp):
    @ship.tool(Path("nested/page/widget.tsx"))
    def my_tool():
        pass

    resource_call = mock_mcp._resource_calls[-1]
    assert resource_call["uri"] == "ui://nested/page"


def test_sets_meta_ui(ship, mock_mcp):
    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    tool_call = mock_mcp._tool_calls[-1]
    assert "ui" in tool_call["meta"]
    assert tool_call["meta"]["ui"]["resourceUri"] == "ui://simple"


def test_preserves_existing_meta(ship, mock_mcp):
    @ship.tool(Path("simple/widget.tsx"), meta={"custom": "value"})
    def my_tool():
        pass

    tool_call = mock_mcp._tool_calls[-1]
    assert tool_call["meta"]["custom"] == "value"
    assert "ui" in tool_call["meta"]


def test_registers_mcp_tool(ship, mock_mcp):
    @ship.tool(Path("simple/widget.tsx"), name="my_tool", title="My Tool", description="desc")
    def my_tool():
        pass

    mock_mcp.tool.assert_called_once()
    call_kwargs = mock_mcp._tool_calls[-1]
    assert call_kwargs["name"] == "my_tool"
    assert call_kwargs["title"] == "My Tool"
    assert call_kwargs["description"] == "desc"


def test_registers_mcp_resource(ship, mock_mcp):
    @ship.tool(Path("simple/widget.tsx"), name="my_tool", title="My Tool", description="desc")
    def my_tool():
        pass

    mock_mcp.resource.assert_called_once()
    call_kwargs = mock_mcp._resource_calls[-1]
    assert call_kwargs["uri"] == "ui://simple"
    assert call_kwargs["mime_type"] == "text/html;profile=mcp-app"


async def test_resource_reads_js(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "console.log('hello');" in html
    assert '<script type="module">' in html


async def test_resource_includes_css_when_present(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    out = ship_output / "simple/client.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("console.log('hello');", encoding="utf-8")
    (ship_output / "simple/client.css").write_text("body { color: red; }", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<style>" in html
    assert "body { color: red; }" in html


async def test_resource_omits_css_when_absent(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<style>" not in html


async def test_resource_uses_views_dot_gdansk_output(mock_mcp, pages_dir):
    ship = Ship(mcp=mock_mcp, views=pages_dir)
    assert ship.output == pages_dir / ".gdansk"

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = pages_dir / ".gdansk" / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('resolved');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "console.log('resolved');" in html


async def test_resource_raises_friendly_error_when_js_missing(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    handler = mock_mcp._resource_calls[-1]["handler"]

    with pytest.raises(FileNotFoundError, match="Has the bundler been run"):
        await handler()


async def test_resource_injects_html_when_effective_ssr_true(mock_mcp, pages_dir, tmp_path):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True)
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")
    server_js_path = ship_output / "simple/server.js"
    server_js_path.parent.mkdir(parents=True, exist_ok=True)
    server_js_path.write_text('Deno.core.ops.op_gdansk_set_html("<p>server</p>");', encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "<p>server</p>"
        html = await handler()

    assert '<div id="root"><p>server</p></div>' in html


async def test_resource_caches_ssr_html_by_default(mock_mcp, pages_dir, tmp_path):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True)
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")
    server_js_path = ship_output / "simple/server.js"
    server_js_path.parent.mkdir(parents=True, exist_ok=True)
    server_js_path.write_text('Deno.core.ops.op_gdansk_set_html("<p>server</p>");', encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "<p>server</p>"
        first_html = await handler()
        second_html = await handler()

    assert first_html == second_html
    mock_run.assert_awaited_once()


async def test_resource_does_not_cache_when_disabled(mock_mcp, pages_dir, tmp_path):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True, cache_html=False)
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")
    server_js_path = ship_output / "simple/server.js"
    server_js_path.parent.mkdir(parents=True, exist_ok=True)
    server_js_path.write_text('Deno.core.ops.op_gdansk_set_html("<p>server</p>");', encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "<p>server</p>"
        await handler()
        await handler()

    assert mock_run.await_count == 2


async def test_resource_invalidates_cache_when_client_bundle_changes(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('one');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    first_html = await handler()
    js_path.write_text("console.log('two two');", encoding="utf-8")
    second_html = await handler()

    assert "console.log('one');" in first_html
    assert "console.log('two two');" in second_html


async def test_resource_invalidates_cache_when_css_presence_changes(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    first_html = await handler()
    (ship_output / "simple/client.css").write_text("body { color: blue; }", encoding="utf-8")
    second_html = await handler()

    assert "<style>" not in first_html
    assert "<style>" in second_html
    assert "body { color: blue; }" in second_html


async def test_resource_skips_runtime_and_html_when_effective_ssr_false(ship, mock_mcp, tmp_path):
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        html = await handler()

    assert '<div id="root"></div>' in html
    mock_run.assert_not_awaited()


async def test_resource_raises_when_ssr_bundle_missing(mock_mcp, pages_dir, tmp_path):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True)
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with pytest.raises(FileNotFoundError, match="SSR bundled output"):
        await handler()


async def test_resource_propagates_runtime_error_fail_fast(mock_mcp, pages_dir, tmp_path):
    ship = Ship(mcp=mock_mcp, views=pages_dir, ssr=True)
    ship_output = tmp_path / "output"
    object.__setattr__(ship, "output", ship_output)

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship_output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")
    server_js_path = ship_output / "simple/server.js"
    server_js_path.parent.mkdir(parents=True, exist_ok=True)
    server_js_path.write_text('Deno.core.ops.op_gdansk_set_html("<p>server</p>");', encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    with patch("gdansk.core.run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            await handler()


async def test_constructor_metadata_applies_to_tool_resource(mock_mcp, pages_dir, tmp_path):
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        metadata={
            "title": "Root App",
            "description": "Shared description",
            "openGraph": {"title": "Shared OG"},
        },
    )
    object.__setattr__(ship, "output", tmp_path / "output")

    @ship.tool(Path("simple/widget.tsx"))
    def my_tool():
        pass

    js_path = ship.output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<title>Root App</title>" in html
    assert '<meta name="description" content="Shared description" />' in html
    assert '<meta property="og:title" content="Shared OG" />' in html


async def test_tool_metadata_overrides_constructor_metadata_shallowly(mock_mcp, pages_dir, tmp_path):
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        metadata={
            "description": "Shared description",
            "openGraph": {"title": "Shared OG", "description": "Shared OG description"},
        },
    )
    object.__setattr__(ship, "output", tmp_path / "output")

    @ship.tool(
        Path("simple/widget.tsx"),
        metadata={"title": "Tool Title", "openGraph": {"title": "Tool OG"}},
    )
    def my_tool():
        pass

    js_path = ship.output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    html = await handler()

    assert "<title>Tool Title</title>" in html
    assert '<meta name="description" content="Shared description" />' in html
    assert '<meta property="og:title" content="Tool OG" />' in html
    assert "Shared OG description" not in html


async def test_metadata_merge_is_non_mutating(mock_mcp, pages_dir, tmp_path):
    base_metadata: Metadata = {"openGraph": {"title": "Shared OG"}}
    tool_metadata: Metadata = {"openGraph": {"title": "Tool OG"}}
    ship = Ship(mcp=mock_mcp, views=pages_dir, metadata=base_metadata)
    object.__setattr__(ship, "output", tmp_path / "output")

    @ship.tool(Path("simple/widget.tsx"), metadata=tool_metadata)
    def my_tool():
        pass

    js_path = ship.output / "simple/client.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("console.log('hello');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    await handler()

    assert base_metadata == {"openGraph": {"title": "Shared OG"}}
    assert tool_metadata == {"openGraph": {"title": "Tool OG"}}


def test_returns_original_function(ship):
    def my_tool():
        return "original"

    result = ship.tool(Path("simple/widget.tsx"))(my_tool)
    assert result is my_tool
    assert result() == "original"


# --- Template rendering ---


def test_inlines_css():
    js = "console.log('hello');"
    css = "body { color: red; }"
    html = ENV.render_template(Ship._template, js=js, css=css, metadata=None)

    assert "<style>" in html
    assert css in html
    assert js in html


def test_no_css():
    js = "console.log('hello');"
    html = ENV.render_template(Ship._template, js=js, css="", metadata=None)

    assert "<style>" not in html
    assert js in html


def test_html_structure():
    js = "console.log('test');"
    html = ENV.render_template(Ship._template, js=js, css="", metadata=None)

    assert html.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8" />' in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1" />' in html
    assert '<div id="root"></div>' in html
    assert '<script type="module">' in html


def test_js_injected_in_script_tag():
    js = "const x = 42;"
    html = ENV.render_template(Ship._template, js=js, css="", metadata=None)

    script_start = html.index('<script type="module">')
    script_end = html.index("</script>")
    script_content = html[script_start:script_end]
    assert js in script_content


def test_html_rendered_in_root():
    js = "const x = 42;"
    html = ENV.render_template(Ship._template, js=js, css="", html="<span>server</span>", metadata=None)

    assert '<div id="root"><span>server</span></div>' in html
