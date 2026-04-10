from pathlib import Path

import pytest

from gdansk.core import Ship
from gdansk.widget_meta import WidgetMeta, widget_meta_to_dict


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")
    return views


def test_widget_resource_meta_defaults_to_base_url_origin(views_path: Path):
    ship = Ship(views=views_path, base_url="https://example.com/app")

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    resource = ship._widget_manager[Path("hello/widget.tsx")].resource
    assert resource.meta == {
        "ui": {
            "csp": {
                "connectDomains": ["https://example.com"],
                "resourceDomains": ["https://example.com"],
            },
            "domain": "https://example.com",
        },
    }
    assert ship._widget_manager[Path("hello/widget.tsx")].tool.meta == {"ui": {"resourceUri": "ui://hello"}}


def test_widget_resource_meta_is_unset_without_base_url_or_overrides(views_path: Path):
    ship = Ship(views=views_path)

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    assert ship._widget_manager[Path("hello/widget.tsx")].resource.meta is None


def test_ship_resource_meta_extends_default_resource_meta(views_path: Path):
    widget_meta: WidgetMeta = {
        "openai": {
            "widgetDescription": "Shared widget description",
        },
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com/v1"],
                "resource_domains": ["https://cdn.example.com/assets"],
            },
        },
    }
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
        widget_meta=widget_meta,
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    assert ship._widget_manager[Path("hello/widget.tsx")].resource.meta == {
        "openai/widgetDescription": "Shared widget description",
        "ui": {
            "csp": {
                "connectDomains": ["https://example.com", "https://api.example.com"],
                "resourceDomains": ["https://example.com", "https://cdn.example.com"],
            },
            "domain": "https://example.com",
        },
    }


def test_widget_resource_meta_overrides_domain_and_augments_csp(views_path: Path):
    ship_widget_meta: WidgetMeta = {
        "openai": {
            "widgetDescription": "Shared widget description",
        },
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://cdn.example.com"],
            },
        },
    }
    widget_widget_meta: WidgetMeta = {
        "openai": {
            "widgetDescription": "Widget-specific description",
        },
        "ui": {
            "csp": {
                "connect_domains": ["https://api.partner.example.com/v2"],
                "frame_domains": ["https://embed.example.com/app"],
                "resource_domains": ["https://cdn.example.com/assets", "https://images.example.com/library"],
            },
            "domain": "https://widgets.example.com/app",
        },
    }
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
        widget_meta=ship_widget_meta,
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", widget_meta=widget_widget_meta)
    def hello() -> None:
        return None

    assert ship._widget_manager[Path("hello/widget.tsx")].resource.meta == {
        "openai/widgetDescription": "Widget-specific description",
        "ui": {
            "csp": {
                "connectDomains": [
                    "https://example.com",
                    "https://api.example.com",
                    "https://api.partner.example.com",
                ],
                "frameDomains": ["https://embed.example.com"],
                "resourceDomains": [
                    "https://example.com",
                    "https://cdn.example.com",
                    "https://images.example.com",
                ],
            },
            "domain": "https://widgets.example.com",
        },
    }


def test_ship_rejects_invalid_resource_meta_domain(views_path: Path):
    with pytest.raises(ValueError, match=r"ui\.domain must be an absolute URL with a hostname"):
        Ship(
            views=views_path,
            widget_meta={
                "ui": {
                    "domain": "/relative",
                },
            },
        )


def test_widget_rejects_invalid_resource_meta_csp_domain(views_path: Path):
    ship = Ship(views=views_path)

    with pytest.raises(ValueError, match=r"ui\.csp\.connect_domains must be an absolute URL with a hostname"):

        @ship.widget(
            path=Path("hello/widget.tsx"),
            name="hello",
            widget_meta={"ui": {"csp": {"connect_domains": ["/relative"]}}},
        )
        def hello() -> None:
            return None


def test_widget_meta_to_dict_serializes_nested_openai_slash_keys_and_redirect_domains():
    meta: WidgetMeta = {
        "openai": {
            "widgetDescription": "Shows the widget.",
            "widgetCSP": {"redirect_domains": ["https://partner.example.com/out"]},
        },
        "ui": {"prefersBorder": True},
    }
    assert widget_meta_to_dict(meta) == {
        "openai/widgetDescription": "Shows the widget.",
        "openai/widgetCSP": {"redirect_domains": ["https://partner.example.com/out"]},
        "ui": {"prefersBorder": True},
    }


def test_merge_widget_meta_emits_openai_widget_csp_for_redirect_domains(views_path: Path):
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
        widget_meta={
            "openai": {
                "widgetCSP": {"redirect_domains": ["https://allow.example.com/callback"]},
            },
        },
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    assert ship._widget_manager[Path("hello/widget.tsx")].resource.meta == {
        "openai/widgetCSP": {"redirect_domains": ["https://allow.example.com"]},
        "ui": {
            "csp": {
                "connectDomains": ["https://example.com"],
                "resourceDomains": ["https://example.com"],
            },
            "domain": "https://example.com",
        },
    }
