from __future__ import annotations

import json
from pathlib import Path

import pytest

from gdansk import _core


def test_hello_from_bin() -> None:
    assert _core.hello_from_bin() == "Hello from gdansk!"


def test_bundle_widget_exposes_key_and_path() -> None:
    widget = _core.BundleWidget(key="nested/page", path=Path("nested/page/widget.tsx"))

    assert widget.key == "nested/page"
    assert widget.path == Path("nested/page/widget.tsx")


def test_bundle_widget_rejects_invalid_paths() -> None:
    with pytest.raises(ValueError, match="widget key"):
        _core.BundleWidget(key="../bad", path=Path("../bad/widget.tsx"))

    with pytest.raises(ValueError, match="widget path"):
        _core.BundleWidget(key="hello", path=Path("/hello/widget.tsx"))

    with pytest.raises(ValueError, match="must match widget key"):
        _core.BundleWidget(key="hello", path=Path("other/widget.tsx"))


@pytest.mark.anyio
async def test_bundle_writes_client_css_and_manifest(tmp_path: Path) -> None:
    views = tmp_path / "views"
    _write_react_fixture(views)
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text(
        "export default function App() { return <div>Hello</div>; }\n",
        encoding="utf-8",
    )
    (views / "widgets" / "nested" / "page").mkdir(parents=True)
    (views / "widgets" / "nested" / "page" / "style.css").write_text(
        ".title { color: red; }\n",
        encoding="utf-8",
    )
    (views / "widgets" / "nested" / "page" / "widget.tsx").write_text(
        'import "./style.css";\nexport default function App() { return <div className="title">Nested</div>; }\n',
        encoding="utf-8",
    )

    await _core.bundle(
        [
            _core.BundleWidget(key="hello", path=Path("hello/widget.tsx")),
            _core.BundleWidget(key="nested/page", path=Path("nested/page/widget.tsx")),
        ],
        root=views,
    )

    assert (views / "dist" / "hello" / "client.js").is_file()
    assert (views / "dist" / "nested" / "page" / "client.js").is_file()
    assert ".title{color:red}" in (views / "dist" / "nested" / "page" / "client.css").read_text(encoding="utf-8")

    manifest = json.loads((views / "dist" / "gdansk-manifest.json").read_text(encoding="utf-8"))
    assert manifest["outDir"] == "dist"
    assert manifest["root"] == str(views)
    assert manifest["widgets"]["hello"] == {
        "client": "dist/hello/client.js",
        "css": [],
        "entry": "hello/widget.tsx",
    }
    assert manifest["widgets"]["nested/page"] == {
        "client": "dist/nested/page/client.js",
        "css": ["dist/nested/page/client.css"],
        "entry": "nested/page/widget.tsx",
    }


def _write_react_fixture(root: Path) -> None:
    react = root / "node_modules" / "react"
    react_dom = root / "node_modules" / "react-dom"
    react.mkdir(parents=True)
    react_dom.mkdir(parents=True)
    (react / "package.json").write_text(
        json.dumps(
            {
                "name": "react",
                "type": "module",
                "exports": {
                    ".": "./index.js",
                    "./jsx-runtime": "./jsx-runtime.js",
                },
            },
        ),
        encoding="utf-8",
    )
    (react / "index.js").write_text(
        "const StrictMode = Symbol.for('react.strict_mode');\n"
        "function createElement(type, props, ...children) { return { type, props, children }; }\n"
        "export { StrictMode, createElement };\n"
        "export default { StrictMode, createElement };\n",
        encoding="utf-8",
    )
    (react / "jsx-runtime.js").write_text(
        "export function jsx(type, props) { return { type, props }; }\n"
        "export const jsxs = jsx;\n"
        "export const Fragment = Symbol.for('react.fragment');\n",
        encoding="utf-8",
    )
    (react_dom / "package.json").write_text(
        json.dumps(
            {
                "name": "react-dom",
                "type": "module",
                "exports": {
                    "./client": "./client.js",
                },
            },
        ),
        encoding="utf-8",
    )
    (react_dom / "client.js").write_text(
        "export function createRoot() { return { render() {} }; }\nexport function hydrateRoot() {}\n",
        encoding="utf-8",
    )
