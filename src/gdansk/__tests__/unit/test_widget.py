from copy import deepcopy
from pathlib import Path

import pytest

from gdansk.core import Ship
from gdansk.widget import WidgetMeta, transform


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")
    return views


def test_transform_renames_widget_metadata():
    meta: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://persistent.oaistatic.com"],
            },
            "domain": "https://myapp.example.com",
        },
        "openai": {
            "widget_description": "Shows an interactive zoo directory rendered by get_zoo_animals.",
        },
    }

    assert transform(meta) == {
        "ui": {
            "csp": {
                "connectDomains": ["https://api.example.com"],
                "resourceDomains": ["https://persistent.oaistatic.com"],
            },
            "domain": "https://myapp.example.com",
        },
        "openai/widgetDescription": "Shows an interactive zoo directory rendered by get_zoo_animals.",
    }


def test_transform_flattens_openai_metadata():
    meta: WidgetMeta = {
        "openai": {
            "tool_invocation": {
                "invoking": "Loading animals",
                "invoked": "Animals loaded",
            },
            "file_params": ["photo"],
        },
    }

    assert transform(meta) == {
        "openai/toolInvocation/invoking": "Loading animals",
        "openai/toolInvocation/invoked": "Animals loaded",
        "openai/fileParams": ["photo"],
    }


def test_ship_widget_sets_default_tool_and_resource_metadata(views_path: Path):
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
            "domain": "https://example.com/app",
        },
        "openai/widgetDescription": "Widget description",
    }


def test_ship_widget_preserves_explicit_metadata(views_path: Path):
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
                "connectDomains": ["https://api.example.com"],
            },
        },
        "openai/widgetDescription": "Explicit widget description",
    }


def test_ship_widget_does_not_mutate_meta_input(views_path: Path):
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
