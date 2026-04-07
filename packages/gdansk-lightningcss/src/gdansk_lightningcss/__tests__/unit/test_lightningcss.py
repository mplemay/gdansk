from __future__ import annotations

from gdansk_bundler import Bundler

from gdansk_lightningcss import LightningCssPlugin, transform_css


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
