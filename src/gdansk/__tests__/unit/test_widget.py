from copy import deepcopy

from gdansk.widget import WidgetMeta, transform


def test_transform_maps_resource_style_ui_and_csp_to_apps_sdk_shape():
    """Aligns with component resource _meta: ui.prefersBorder, domain, csp.* in camelCase."""
    meta: WidgetMeta = {
        "ui": {
            "prefers_border": True,
            "domain": "https://myapp.example.com",
            "csp": {
                "connect_domains": ["https://api.myapp.example.com"],
                "resource_domains": ["https://*.oaistatic.com"],
                "frame_domains": ["https://*.example-embed.com"],
            },
        },
        "openai": {
            "widget_description": "Summary for the model.",
        },
    }

    assert transform(meta) == {
        "ui": {
            "prefersBorder": True,
            "domain": "https://myapp.example.com",
            "csp": {
                "connectDomains": ["https://api.myapp.example.com"],
                "resourceDomains": ["https://*.oaistatic.com"],
                "frameDomains": ["https://*.example-embed.com"],
            },
        },
        "openai/widgetDescription": "Summary for the model.",
    }


def test_transform_flattens_tool_openai_keys_and_ui_resource_uri():
    """Tool descriptor style: ui.resourceUri plus flat openai/toolInvocation/* keys."""
    meta: WidgetMeta = {
        "ui": {"resource_uri": "ui://widget/kanban-board.html"},
        "openai": {
            "tool_invocation": {
                "invoking": "Preparing the board…",
                "invoked": "Board ready.",
            },
        },
    }

    assert transform(meta) == {
        "ui": {"resourceUri": "ui://widget/kanban-board.html"},
        "openai/toolInvocation/invoking": "Preparing the board…",
        "openai/toolInvocation/invoked": "Board ready.",
    }


def test_transform_flattens_file_params():
    meta: WidgetMeta = {
        "openai": {
            "file_params": ["photo"],
        },
    }

    assert transform(meta) == {
        "openai/fileParams": ["photo"],
    }


def test_transform_does_not_mutate_input():
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

    transform(meta)

    assert meta == original
