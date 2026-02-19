from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from anyio import Path as APath

from gdansk._core import Runtime, bundle


def _write_ssr_modules(root: Path, *, throw_on_render: bool = False) -> None:
    react_dir = root / "node_modules" / "react"
    react_dir.mkdir(parents=True, exist_ok=True)
    (react_dir / "package.json").write_text(
        (
            "{\n"
            '  "name": "react",\n'
            '  "private": true,\n'
            '  "type": "module",\n'
            '  "exports": {\n'
            '    ".": "./index.js"\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    (react_dir / "index.js").write_text(
        "export function createElement(type, props, ...children) {\n"
        "  return { type, props: { ...(props ?? {}), children } };\n"
        "}\n",
        encoding="utf-8",
    )

    react_dom_dir = root / "node_modules" / "react-dom"
    react_dom_dir.mkdir(parents=True, exist_ok=True)
    (react_dom_dir / "package.json").write_text(
        (
            "{\n"
            '  "name": "react-dom",\n'
            '  "private": true,\n'
            '  "type": "module",\n'
            '  "exports": {\n'
            '    "./server": "./server.js"\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    if throw_on_render:
        (react_dom_dir / "server.js").write_text(
            "export function renderToString() {\n  throw new Error('ssr boom');\n}\n",
            encoding="utf-8",
        )
        return
    (react_dom_dir / "server.js").write_text(
        "export function renderToString(node) {\n"
        "  if (typeof node?.type === 'function') {\n"
        "    return renderToString(node.type(node.props ?? {}));\n"
        "  }\n"
        "  const children = Array.isArray(node?.props?.children) ? node.props.children.join('') : '';\n"
        "  return `<${node.type}>${children}</${node.type}>`;\n"
        "}\n",
        encoding="utf-8",
    )


async def _wait_for_file_or_task_failure(
    task: asyncio.Task[None],
    output_path: Path,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    path = APath(output_path)
    while loop.time() < deadline:
        if await path.exists():
            return
        if task.done():
            exc = task.exception()
            message = f"bundle task ended before emitting {output_path}: {exc!r}"
            pytest.fail(message)
        await asyncio.sleep(0.05)

    message = f"timed out waiting for bundle output: {output_path}"
    pytest.fail(message)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_writes_default_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    await bundle({Path("main.tsx")})

    assert (tmp_path / ".gdansk" / "main.js").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_writes_nested_output_in_custom_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "home" / "page.tsx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const home = 1;\n", encoding="utf-8")

    await bundle({Path("home/page.tsx")}, output=Path("custom-out"))

    assert (tmp_path / "custom-out" / "home" / "page.js").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_empty_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        await bundle(set())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_non_jsx_or_tsx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.ts").write_text("export const value = 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.tsx or \.jsx"):
        await bundle({Path("main.ts")})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_input_outside_cwd(tmp_path, tmp_path_factory, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside_root = tmp_path_factory.mktemp("outside")
    outside_file = outside_root / "outside.tsx"
    outside_file.write_text("export const value = 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside cwd"):
        await bundle({outside_file})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_rejects_output_collisions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.tsx").write_text("export const a = 1;\n", encoding="utf-8")
    (tmp_path / "a.jsx").write_text("export const b = 2;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="same output"):
        await bundle({Path("a.tsx"), Path("a.jsx")})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_dev_mode_can_run_in_background_and_cancel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    task = asyncio.ensure_future(bundle({Path("main.tsx")}, dev=True))
    await _wait_for_file_or_task_failure(task, tmp_path / ".gdansk" / "main.js")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_outputs_css_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "page.css").write_text("body { color: red; }\n", encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    await bundle({Path("page.tsx")})

    assert (tmp_path / ".gdansk" / "page.js").exists()
    assert (tmp_path / ".gdansk" / "page.css").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_resolves_css_package_style_exports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    package_dir = tmp_path / "node_modules" / "tw-animate-css"
    (package_dir / "dist").mkdir(parents=True, exist_ok=True)
    (package_dir / "package.json").write_text(
        """
{
  "name": "tw-animate-css",
  "exports": {
    ".": {
      "style": "./dist/tw-animate.css"
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "dist" / "tw-animate.css").write_text(
        "body { color: green; }\n",
        encoding="utf-8",
    )

    (tmp_path / "page.css").write_text('@import "tw-animate-css";\n', encoding="utf-8")
    (tmp_path / "page.tsx").write_text(
        'import "./page.css";\nexport const page = 1;\n',
        encoding="utf-8",
    )

    await bundle({Path("page.tsx")})

    css_output = tmp_path / ".gdansk" / "page.css"
    assert css_output.exists()
    assert "green" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_accepts_minify_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tsx").write_text("export const value = 1;\n", encoding="utf-8")

    await bundle({Path("main.tsx")}, minify=False)

    assert (tmp_path / ".gdansk" / "main.js").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_server_entrypoint_mode_writes_executable_ssr_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ssr_modules(tmp_path)
    (tmp_path / "apps" / "simple").mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps" / "simple" / "app.tsx").write_text(
        'import { createElement } from "react";\n'
        "export default function App() {\n"
        "  return createElement('div', null, 'ok');\n"
        "}\n",
        encoding="utf-8",
    )

    await bundle(
        {Path("apps/simple/app.tsx")},
        output=Path(".gdansk/.ssr"),
        app_entrypoint_mode=True,
        server_entrypoint_mode=True,
    )

    output_js = tmp_path / ".gdansk" / ".ssr" / "apps" / "simple" / "app.js"
    assert output_js.exists()

    runtime = Runtime()
    ssr_html = runtime(f"{output_js.read_text(encoding='utf-8')}\n;globalThis.__gdansk_ssr_html")
    assert ssr_html == "<div>ok</div>"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bundle_server_entrypoint_mode_runtime_error_surfaces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ssr_modules(tmp_path, throw_on_render=True)
    (tmp_path / "apps" / "simple").mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps" / "simple" / "app.tsx").write_text(
        "export default function App() {\n  return null;\n}\n",
        encoding="utf-8",
    )

    await bundle(
        {Path("apps/simple/app.tsx")},
        output=Path(".gdansk/.ssr"),
        app_entrypoint_mode=True,
        server_entrypoint_mode=True,
    )

    output_js = tmp_path / ".gdansk" / ".ssr" / "apps" / "simple" / "app.js"
    runtime = Runtime()
    with pytest.raises(RuntimeError, match="Execution error"):
        runtime(f"{output_js.read_text(encoding='utf-8')}\n;globalThis.__gdansk_ssr_html")


@pytest.mark.integration
def test_runtime_constructs_and_evaluates_expression():
    runtime = Runtime()
    assert runtime("1 + 2") == 3


@pytest.mark.integration
def test_runtime_preserves_state_across_calls():
    runtime = Runtime()
    runtime("globalThis.counter = 1")
    assert runtime("counter += 2; counter") == 3


@pytest.mark.integration
def test_runtime_converts_nested_json_like_values():
    runtime = Runtime()
    assert runtime('({ ok: true, values: [1, { name: "gdansk" }, null] })') == {
        "ok": True,
        "values": [1, {"name": "gdansk"}, None],
    }


@pytest.mark.integration
def test_runtime_reports_execution_errors():
    runtime = Runtime()
    with pytest.raises(RuntimeError, match="Execution error"):
        runtime("throw new Error('boom')")


@pytest.mark.integration
def test_runtime_rejects_unsupported_values():
    runtime = Runtime()
    with pytest.raises(ValueError, match="Cannot deserialize value"):
        runtime("undefined")


@pytest.mark.integration
def test_runtime_returns_expected_python_types():
    runtime = Runtime()

    assert type(runtime("true")) is bool
    assert type(runtime("123")) is int
    assert type(runtime("1.25")) is float
    assert type(runtime("'hello'")) is str
    assert type(runtime("[1, 2, 3]")) is list
    assert type(runtime("({ ok: true })")) is dict
    assert runtime("null") is None


@pytest.mark.integration
@pytest.mark.parametrize("code", ["Symbol('x')", "1n", "Promise.resolve(1)", "0/0", "1/0"])
def test_runtime_rejects_additional_unsupported_values(code):
    runtime = Runtime()
    with pytest.raises(ValueError, match="Cannot deserialize value"):
        runtime(code)


@pytest.mark.integration
def test_runtime_recovers_after_execution_error():
    runtime = Runtime()
    with pytest.raises(RuntimeError, match="Execution error"):
        runtime("throw new Error('boom')")
    assert runtime("1 + 1") == 2


@pytest.mark.integration
def test_runtime_recovers_after_deserialize_error():
    runtime = Runtime()
    with pytest.raises(ValueError, match="Cannot deserialize value"):
        runtime("Symbol('x')")
    assert runtime("1 + 2") == 3


@pytest.mark.integration
def test_runtime_supports_empty_containers():
    runtime = Runtime()
    assert runtime("({})") == {}
    assert runtime("[]") == []


@pytest.mark.integration
def test_runtime_supports_unicode_strings():
    runtime = Runtime()
    assert runtime("'café 👋'") == "café 👋"
