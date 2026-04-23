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
    assert resource["openai/widgetPrefersBorder"] is False


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


def test_transform_appends_base_url_to_resource_domains():
    widget: WidgetMeta = {
        "ui": {
            "csp": {
                "resource_domains": ["https://cdn.example.com"],
            },
        },
    }
    extra: WidgetExtra = {"uri": "ui://x", "base_url": "https://example.com/app", "description": None}

    _tool, resource = transform(widget, extra)

    assert resource["ui"]["csp"]["resourceDomains"] == [
        "https://cdn.example.com",
        "https://example.com",
    ]


def test_transform_appends_base_url_to_connect_domains():
    widget: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
            },
        },
    }
    extra: WidgetExtra = {"uri": "ui://x", "base_url": "https://example.com/app", "description": None}

    _tool, resource = transform(widget, extra)

    assert resource["ui"]["csp"]["connectDomains"] == [
        "https://api.example.com",
        "https://example.com",
    ]


def test_transform_synthesizes_csp_from_base_url_without_domain():
    widget: WidgetMeta = {}
    extra: WidgetExtra = {"uri": "ui://x", "base_url": "https://example.com/app", "description": None}

    _tool, resource = transform(widget, extra)

    assert resource["ui"]["csp"]["connectDomains"] == ["https://example.com"]
    assert resource["ui"]["csp"]["resourceDomains"] == ["https://example.com"]
    assert "domain" not in resource["ui"]
    assert "openai/widgetDomain" not in resource


def test_transform_does_not_duplicate_base_url_in_connect_domains():
    widget: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com", "https://example.com"],
            },
        },
    }
    extra: WidgetExtra = {"uri": "ui://x", "base_url": "https://example.com/app", "description": None}

    _tool, resource = transform(widget, extra)

    assert resource["ui"]["csp"]["connectDomains"] == [
        "https://api.example.com",
        "https://example.com",
    ]


def test_transform_does_not_duplicate_base_url_in_resource_domains():
    widget: WidgetMeta = {
        "ui": {
            "csp": {
                "resource_domains": ["https://cdn.example.com", "https://example.com"],
            },
        },
    }
    extra: WidgetExtra = {"uri": "ui://x", "base_url": "https://example.com/app", "description": None}

    _tool, resource = transform(widget, extra)

    assert resource["ui"]["csp"]["resourceDomains"] == [
        "https://cdn.example.com",
        "https://example.com",
    ]
