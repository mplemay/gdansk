from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.protocol import JsPluginSpec


def test_js_plugin_spec_accepts_path_like_specifier():
    spec = JsPluginSpec(specifier=Path("plugins/append-comment.mjs"), options={"comment": "ok"})

    assert spec.specifier == "plugins/append-comment.mjs"
    assert spec.options == {"comment": "ok"}


def test_js_plugin_spec_rejects_empty_specifier():
    with pytest.raises(ValueError, match="specifier"):
        JsPluginSpec(specifier="", options={})


def test_js_plugin_spec_rejects_non_json_serializable_options():
    with pytest.raises(TypeError, match="JSON serializable"):
        JsPluginSpec(specifier="plugins/append-comment.mjs", options={"bad": {1, 2}})
