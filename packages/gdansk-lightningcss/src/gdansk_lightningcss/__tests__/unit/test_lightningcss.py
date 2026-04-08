from __future__ import annotations

import importlib
from unittest.mock import Mock, patch

from gdansk_bundler import Bundler

from gdansk_lightningcss import LightningCssPlugin, transform_css

bundle_impl = importlib.import_module("gdansk_lightningcss.bundle")


def test_bundler_accepts_lightning_css_plugin() -> None:
    b = Bundler(plugins=[LightningCssPlugin()])
    assert b is not None


def test_transform_css_parses_nested_rules() -> None:
    code = ".a {\n  .b { color: red; }\n}\n"
    out = transform_css(code, "/fixture/a.css", minify=False)
    assert "color" in out
    assert "red" in out
    assert ".a" in out
    assert ".b" in out


def test_transform_css_minify_removes_whitespace() -> None:
    code = ".x { color: blue; }\n"
    out = transform_css(code, "/fixture/x.css", minify=True)
    assert "\n" not in out.strip()
    assert ".x{color:" in out


def test_lightning_css_plugin_defers_non_css() -> None:
    p = LightningCssPlugin()
    assert p.transform("const x = 1", "/a.js", "js") is None


def test_lightning_css_plugin_transforms_css() -> None:
    p = LightningCssPlugin(minify=True)
    got = p.transform(".a { color: green; }", "/z.css", "css")
    assert got is not None
    assert "green" in got["code"]


def test_synthetic_import_specifier_uses_absolute_path_when_relpath_crosses_drives() -> None:
    source_path = Mock()
    resolved_source_path = Mock()
    source_path.resolve.return_value = resolved_source_path
    resolved_source_path.relative_to.side_effect = ValueError("not relative")
    resolved_source_path.as_posix.return_value = "D:/repo/styles.css"

    module_dir = Mock()
    module_dir.resolve.return_value = Mock()
    msg = "path is on mount 'D:', start on mount 'C:'"

    with patch("gdansk_lightningcss.bundle.os.path.relpath", side_effect=ValueError(msg)):
        assert bundle_impl._synthetic_import_specifier(source_path, module_dir=module_dir) == "D:/repo/styles.css"
