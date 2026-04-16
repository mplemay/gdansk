from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from starlette.staticfiles import StaticFiles

from gdansk.core import Ship

if TYPE_CHECKING:
    from gdansk.widget import WidgetMeta


def test_widget_rejects_missing_widget_file(views_path: Path):
    ship = Ship(views=views_path)

    with pytest.raises(FileNotFoundError, match="is not a file"):
        ship.widget(path=Path("missing/widget.tsx"))


def test_ship_uses_default_runtime_host_and_port(views_path: Path):
    ship = Ship(views=views_path)

    assert ship._host == "127.0.0.1"
    assert ship._port == 13714
    assert isinstance(ship.assets, StaticFiles)
    assert ship.assets is ship.assets
    assert Path(str(ship.assets.directory)) == views_path / "dist"


def test_ship_rejects_invalid_runtime_port(views_path: Path):
    with pytest.raises(ValueError, match="runtime port"):
        Ship(views=views_path, port=0)


def test_ship_rejects_invalid_base_url(views_path: Path):
    with pytest.raises(ValueError, match="base URL"):
        Ship(views=views_path, base_url="/relative")


def test_ship_widgets_root_is_views_join_widgets(views_path: Path):
    ship = Ship(views=views_path)
    assert ship._widgets_root == views_path / "widgets"


def test_ship_widget_default_tool_and_resource_metadata(views_path: Path):
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", description="Widget description")
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    assert spec.tool.meta == {
        "ui": {
            "resourceUri": "ui://hello",
        },
    }
    assert spec.resource.meta == {
        "ui": {
            "domain": "https://example.com",
            "csp": {
                "connectDomains": ["https://example.com"],
                "resourceDomains": ["https://example.com"],
            },
        },
        "openai/widgetDescription": "Widget description",
        "openai/widgetDomain": "https://example.com",
    }


def test_ship_widget_preserves_explicit_metadata_split(views_path: Path):
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "ui": {
            "resource_uri": "ui://custom",
            "prefers_border": True,
            "domain": "https://widgets.example.com",
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://cdn.example.com"],
            },
        },
        "openai": {
            "widget_description": "Explicit widget description",
            "tool_invocation": {
                "invoking": "Calling tool",
                "invoked": "Tool complete",
            },
            "file_params": ["photo"],
        },
    }

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", description="Fallback description", meta=meta)
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    assert spec.tool.meta == {
        "ui": {
            "resourceUri": "ui://custom",
        },
        "openai/toolInvocation/invoking": "Calling tool",
        "openai/toolInvocation/invoked": "Tool complete",
        "openai/fileParams": ["photo"],
    }
    assert spec.resource.meta == {
        "ui": {
            "prefersBorder": True,
            "domain": "https://widgets.example.com",
            "csp": {
                "connectDomains": [
                    "https://api.example.com",
                    "https://example.com",
                ],
                "resourceDomains": [
                    "https://cdn.example.com",
                    "https://example.com",
                ],
            },
        },
        "openai/widgetDescription": "Explicit widget description",
        "openai/widgetPrefersBorder": True,
        "openai/widgetDomain": "https://widgets.example.com",
    }


def test_ship_widget_description_fallback_for_resource_meta(views_path: Path):
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
            },
        },
    }

    @ship.widget(
        path=Path("hello/widget.tsx"),
        name="hello",
        description="From decorator",
        meta=meta,
    )
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    resource_meta = spec.resource.meta
    assert resource_meta is not None
    assert resource_meta["openai/widgetDescription"] == "From decorator"


def test_ship_widget_explicit_widget_description_overrides_decorator(views_path: Path):
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "openai": {
            "widget_description": "From meta",
        },
    }

    @ship.widget(
        path=Path("hello/widget.tsx"),
        name="hello",
        description="From decorator",
        meta=meta,
    )
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    resource_meta = spec.resource.meta
    assert resource_meta is not None
    assert resource_meta["openai/widgetDescription"] == "From meta"


def test_ship_widget_does_not_mutate_meta_input(views_path: Path):
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://cdn.example.com"],
            },
        },
        "openai": {
            "tool_invocation": {
                "invoking": "Calling tool",
                "invoked": "Tool complete",
            },
        },
    }
    original = deepcopy(meta)

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", description="Widget description", meta=meta)
    def hello() -> None:
        return None

    assert meta == original
