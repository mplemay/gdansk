from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.protocol import VitePlugin


def test_vite_plugin_accepts_path_like_specifier():
    spec = VitePlugin(specifier=Path("plugins/append-comment.mjs"), options={"comment": "ok"})

    assert spec.specifier == "plugins/append-comment.mjs"
    assert spec.options == {"comment": "ok"}


def test_vite_plugin_accepts_bare_package_specifier():
    spec = VitePlugin(specifier="@tailwindcss/vite")

    assert spec.specifier == "@tailwindcss/vite"
    assert spec.options == {}


def test_vite_plugin_rejects_empty_specifier():
    with pytest.raises(ValueError, match="specifier"):
        VitePlugin(specifier="", options={})


def test_vite_plugin_rejects_non_json_serializable_options():
    with pytest.raises(TypeError, match="JSON serializable"):
        VitePlugin(specifier="plugins/append-comment.mjs", options={"bad": {1, 2}})
