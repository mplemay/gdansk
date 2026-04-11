from gdansk.widget import WidgetExtra, WidgetMeta, transform


def test_transform_prefers_border_false_is_emitted():
    widget: WidgetMeta = {
        "ui": {
            "prefers_border": False,
        },
    }
    extra: WidgetExtra = {"uri": "ui://x", "base_url": None, "description": None}
    _tool, resource = transform(widget, extra)
    assert resource["ui"]["prefersBorder"] is False


def test_transform_openai_tool_descriptor_extensions():
    widget: WidgetMeta = {
        "openai": {
            "widget_accessible": True,
            "visibility": "private",
            "security_schemes": [{"type": "noauth"}],
        },
    }
    extra: WidgetExtra = {"uri": "ui://app/widget", "base_url": None, "description": None}
    tool, _resource = transform(widget, extra)
    assert tool["openai/widgetAccessible"] is True
    assert tool["openai/visibility"] == "private"
    assert tool["securitySchemes"] == [{"type": "noauth"}]


def test_transform_maps_all_csp_fields():
    widget: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://cdn.example.com"],
                "frame_domains": ["https://embed.example.com"],
            },
        },
    }
    extra: WidgetExtra = {"uri": "ui://x", "base_url": None, "description": None}
    _tool, resource = transform(widget, extra)
    csp = resource["ui"]["csp"]
    assert csp["connectDomains"] == ["https://api.example.com"]
    assert csp["resourceDomains"] == ["https://cdn.example.com"]
    assert csp["frameDomains"] == ["https://embed.example.com"]
