from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from gdansk_bundler import Bundler, Plugin as BundlerPlugin
from gdansk_lightningcss import bundle_css_paths, transform_css
from gdansk_runtime import Runtime as JsRuntime, Script
from gdansk_vite import VitePlugin, transform_css_assets

__all__ = ["LightningCSS", "Page", "VitePlugin", "bundle", "run"]

_JS_IMPORT_PATTERN = re.compile(
    r"""(?m)(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?["']([^"']+)["']""",
)
_CSS_STUB_PREFIX = "\0gdansk:css-stub:"
_OUTPUT_DIRNAME = ".gdansk"
_ENTRY_DIRNAME = "__gdansk_entries"
_CSS_ENTRY_DIRNAME = "__gdansk_css_entries"
_RUNTIME_ENTRY_PATH = Path("__gdansk_runtime_eval__.js")
_RUNNER = JsRuntime()
_MODULE_SYNTAX_PATTERN = re.compile(r"(?m)^\s*(?:import|export)\b")


@dataclass(frozen=True, slots=True, kw_only=True)
class Page:
    path: Path
    is_widget: bool = False
    ssr: bool = False
    client: Path = field(init=False)
    server: Path | None = field(init=False)
    css: Path = field(init=False)

    def __post_init__(self) -> None:
        normalized_path = Path(self.path)
        object.__setattr__(self, "path", normalized_path)

        if not self.is_widget:
            stem = normalized_path.with_suffix("")
            object.__setattr__(self, "client", stem.with_suffix(".js"))
            object.__setattr__(self, "css", stem.with_suffix(".css"))
            object.__setattr__(self, "server", stem.with_suffix(".js") if self.ssr else None)
            return

        tool_directory = Path(*normalized_path.parts[1:-1])
        client_stem = tool_directory / "client"
        object.__setattr__(self, "client", client_stem.with_suffix(".js"))
        object.__setattr__(self, "css", client_stem.with_suffix(".css"))
        object.__setattr__(
            self,
            "server",
            (tool_directory / "server").with_suffix(".js") if self.ssr else None,
        )


class LightningCSS(BundlerPlugin):
    def __init__(self) -> None:
        super().__init__(id="lightningcss")

    def __repr__(self) -> str:
        return "LightningCSS()"


@dataclass(frozen=True, slots=True)
class _NormalizedPage:
    absolute_path: Path
    import_path: str
    page: Page
    client_name: str
    server_name: str | None


@dataclass(frozen=True, slots=True)
class _PageAssets:
    css_paths: tuple[Path, ...]
    js_paths: tuple[Path, ...]
    watch_paths: tuple[Path, ...]


class _CssStubPlugin(BundlerPlugin):
    def __init__(self, *, root: Path) -> None:
        super().__init__(id="gdansk-css-stub")
        self._root = root.resolve()

    def resolve_id(self, specifier: str, importer: str | None) -> str | None:
        if importer is None or not specifier.endswith(".css"):
            return None
        importer_path = Path(importer)
        importer_dir = importer_path.parent if importer_path.suffix else importer_path
        try:
            resolved = _resolve_local_css_import(specifier, importer_dir=importer_dir, root=self._root)
        except ValueError:
            return None
        return _encode_css_stub_id(resolved)

    def load(self, module_id: str) -> dict[str, str] | None:
        if not module_id.startswith(_CSS_STUB_PREFIX):
            return None
        return {"code": "const gdanskCssStub = {};\nexport default gdanskCssStub;\n"}


def _is_relative_specifier(specifier: str) -> bool:
    return specifier.startswith(("./", "../"))


def _relative_import(target: Path, *, from_file: Path) -> str:
    value = Path(os.path.relpath(target, from_file.parent)).as_posix()
    if not value.startswith((".", "/")):
        return f"./{value}"
    return value


def _path_to_posix(path: Path) -> str:
    return path.as_posix()


def _encode_css_stub_id(path: Path) -> str:
    encoded = base64.urlsafe_b64encode(path.as_posix().encode("utf-8")).decode("ascii")
    return f"{_CSS_STUB_PREFIX}{encoded}"


def _resolve_output_dir(*, output: Path | None, cwd: Path) -> Path:
    if output is None:
        return (cwd / _OUTPUT_DIRNAME).resolve()
    return output.resolve() if output.is_absolute() else (cwd / output).resolve()


def _normalize_pages(
    pages: list[Page],
    *,
    cwd: Path,
    output_dir: Path,
) -> list[_NormalizedPage]:
    if not pages:
        msg = "`pages` must not be empty; expected at least one .tsx or .jsx file"
        raise ValueError(msg)

    normalized: list[_NormalizedPage] = []
    output_collisions: dict[Path, str] = {}
    for page in pages:
        candidate = page.path if page.path.is_absolute() else cwd / page.path
        if not candidate.exists():
            msg = f"input path does not exist: {page.path}"
            raise ValueError(msg)
        if not candidate.is_file():
            msg = f"input path is not a file: {page.path}"
            raise ValueError(msg)
        if candidate.suffix not in {".tsx", ".jsx"}:
            msg = f"input path must end in .tsx or .jsx: {page.path}"
            raise ValueError(msg)
        absolute = candidate.resolve()
        try:
            relative = absolute.relative_to(cwd)
        except ValueError as err:
            msg = f"input path must resolve inside cwd {cwd}: {absolute}"
            raise ValueError(msg) from err

        if page.ssr and not page.is_widget:
            msg = f"page cannot set ssr=true when is_widget=false: {page.path}"
            raise ValueError(msg)

        if page.is_widget:
            if relative.name not in {"widget.tsx", "widget.jsx"}:
                msg = f"widget pages must target widget.tsx or widget.jsx: {page.path}"
                raise ValueError(msg)
            if not relative.parts or relative.parts[0] != "widgets":
                msg = f"widget pages must be inside a widgets/ directory: {page.path}"
                raise ValueError(msg)
            if len(relative.parts) < 3:
                msg = f"widget pages must include at least one segment below widgets/: {page.path}"
                raise ValueError(msg)

        client_path = page.client
        collision_key = output_dir / client_path
        import_key = _path_to_posix(relative)
        if collision_key in output_collisions:
            msg = (
                f"multiple pages map to the same output {collision_key}: "
                f"{output_collisions[collision_key]} and {import_key}"
            )
            raise ValueError(msg)
        output_collisions[collision_key] = import_key

        server_name: str | None = None
        if page.server is not None:
            server_collision_key = output_dir / page.server
            if server_collision_key in output_collisions:
                msg = (
                    f"multiple pages map to the same output {server_collision_key}: "
                    f"{output_collisions[server_collision_key]} and {import_key}"
                )
                raise ValueError(msg)
            output_collisions[server_collision_key] = import_key
            server_name = page.server.with_suffix("").as_posix()

        normalized.append(
            _NormalizedPage(
                absolute_path=absolute,
                import_path=relative.as_posix(),
                page=page,
                client_name=page.client.with_suffix("").as_posix(),
                server_name=server_name,
            ),
        )

    normalized.sort(key=lambda item: item.import_path)
    return normalized


def _resolve_local_module(specifier: str, *, importer_dir: Path) -> Path | None:
    if not (_is_relative_specifier(specifier) or Path(specifier).is_absolute()):
        return None

    raw = Path(specifier)
    candidate = raw if raw.is_absolute() else (importer_dir / raw)
    search_order = [
        candidate,
        *[candidate.with_suffix(ext) for ext in (".ts", ".tsx", ".js", ".jsx", ".json") if candidate.suffix == ""],
        *[
            candidate / f"index{ext}"
            for ext in (".ts", ".tsx", ".js", ".jsx", ".json")
            if candidate.is_dir() or candidate.suffix == ""
        ],
    ]
    for path in search_order:
        if path.exists() and path.is_file():
            return path.resolve()
    return None


def _resolve_local_css_import(specifier: str, *, importer_dir: Path, root: Path) -> Path:
    candidate = _resolve_local_module(specifier, importer_dir=importer_dir)
    if candidate is None or candidate.suffix != ".css":
        msg = f'failed to resolve css import "{specifier}"'
        raise ValueError(msg)
    try:
        candidate.relative_to(root)
    except ValueError as err:
        msg = f'failed to resolve css import "{specifier}"'
        raise ValueError(msg) from err
    return candidate


def _scan_js_module_graph(
    entry_path: Path,
    *,
    root: Path,
    seen: set[Path] | None = None,
) -> tuple[set[Path], list[Path]]:
    local_seen = seen or set()
    if entry_path in local_seen:
        return set(), []
    local_seen.add(entry_path)

    js_paths = {entry_path}
    css_paths: list[Path] = []
    source = entry_path.read_text(encoding="utf-8")
    for match in _JS_IMPORT_PATTERN.finditer(source):
        specifier = match.group(1)
        if specifier.endswith(".css"):
            try:
                css_paths.append(
                    _resolve_local_css_import(specifier, importer_dir=entry_path.parent, root=root),
                )
            except ValueError:
                continue
            continue

        child = _resolve_local_module(specifier, importer_dir=entry_path.parent)
        if child is None:
            continue
        if child.suffix == ".css":
            css_paths.append(child)
            continue
        child_js_paths, child_css_paths = _scan_js_module_graph(child, root=root, seen=local_seen)
        js_paths.update(child_js_paths)
        css_paths.extend(child_css_paths)

    ordered_css: list[Path] = []
    seen_css: set[Path] = set()
    for css_path in css_paths:
        if css_path in seen_css:
            continue
        seen_css.add(css_path)
        ordered_css.append(css_path)
    return js_paths, ordered_css


def _collect_page_assets(page: _NormalizedPage, *, root: Path) -> _PageAssets:
    js_paths, css_paths = _scan_js_module_graph(page.absolute_path, root=root)
    watch_paths = tuple(sorted({*js_paths, *css_paths}))
    return _PageAssets(
        css_paths=tuple(css_paths),
        js_paths=tuple(sorted(js_paths)),
        watch_paths=watch_paths,
    )


def _write_client_entry(wrapper_path: Path, *, source_path: Path) -> None:
    import_path = _relative_import(source_path, from_file=wrapper_path)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        f"""import {{ StrictMode, createElement }} from "react";
import {{ createRoot, hydrateRoot }} from "react-dom/client";
import App from "{import_path}";

const root = document.getElementById("root");
if (!root) throw new Error("Expected #root element");
const element = createElement(StrictMode, null, createElement(App));
root.hasChildNodes()?hydrateRoot(root, element):createRoot(root).render(element);
""",
        encoding="utf-8",
    )


def _write_server_entry(wrapper_path: Path, *, source_path: Path) -> None:
    import_path = _relative_import(source_path, from_file=wrapper_path)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        f"""import {{ createElement }} from "react";
import {{ renderToString }} from "react-dom/server";
import App from "{import_path}";

export default function render() {{
  return renderToString(createElement(App));
}}
""",
        encoding="utf-8",
    )


def _prepare_entry_files(
    pages: list[_NormalizedPage],
    *,
    output_dir: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    entry_root = output_dir / _ENTRY_DIRNAME
    if entry_root.exists():
        shutil.rmtree(entry_root)
    client_inputs: dict[str, str] = {}
    server_inputs: dict[str, str] = {}

    for page in pages:
        if page.page.is_widget:
            client_entry = entry_root / "client" / page.page.client
            _write_client_entry(client_entry, source_path=page.absolute_path)
            client_inputs[page.client_name] = str(client_entry)
        else:
            client_inputs[page.client_name] = str(page.absolute_path)

        if page.page.server is not None and page.server_name is not None:
            server_entry = entry_root / "server" / page.page.server
            _write_server_entry(server_entry, source_path=page.absolute_path)
            server_inputs[page.server_name] = str(server_entry)

    return client_inputs, server_inputs


def _should_preserve_tailwind(
    *,
    css_plugins: list[BundlerPlugin],
    vite_plugins: list[VitePlugin],
) -> bool:
    if any(plugin.specifier == "@tailwindcss/vite" for plugin in vite_plugins):
        return True
    return any(
        plugin.__class__.__name__ == "TailwindCssPlugin"
        and plugin.__class__.__module__.startswith("gdansk_tailwindcss")
        for plugin in css_plugins
    )


def _apply_css_plugin_transforms(
    code: str,
    *,
    module_id: Path,
    css_plugins: list[BundlerPlugin],
) -> str:
    current = code
    for plugin in css_plugins:
        plugin_name = getattr(plugin, "id", "")
        if plugin_name == "lightningcss":
            continue
        transform = getattr(plugin, "transform", None)
        if not callable(transform):
            continue
        result = transform(current, str(module_id), "css")
        if not result:
            continue
        replacement = result.get("code")
        if isinstance(replacement, str):
            current = replacement
    return current


def _build_css_outputs(
    pages: list[_NormalizedPage],
    page_assets: dict[Path, _PageAssets],
    *,
    cwd: Path,
    output_dir: Path,
    minify: bool,
    css_plugins: list[BundlerPlugin],
    vite_plugins: list[VitePlugin],
) -> set[Path]:
    watch_files: set[Path] = set()
    preserve_tailwind = _should_preserve_tailwind(css_plugins=css_plugins, vite_plugins=vite_plugins)
    preserve_specifiers = frozenset({"tailwindcss"}) if preserve_tailwind else frozenset()

    for page in pages:
        css_output_path = output_dir / page.page.css
        css_output_path.parent.mkdir(parents=True, exist_ok=True)
        assets = page_assets[page.absolute_path]
        if not assets.css_paths:
            if css_output_path.exists():
                css_output_path.unlink()
            continue

        synthetic_module_id = output_dir / _CSS_ENTRY_DIRNAME / page.page.css
        synthetic_module_id.parent.mkdir(parents=True, exist_ok=True)
        bundled = bundle_css_paths(
            list(assets.css_paths),
            root=cwd,
            module_id=synthetic_module_id,
            minify=False,
            preserve_specifiers=preserve_specifiers,
            finalize=False,
        )
        watch_files.update(bundled.files)

        code = _apply_css_plugin_transforms(
            bundled.code,
            module_id=synthetic_module_id,
            css_plugins=css_plugins,
        )
        code = transform_css(code, str(css_output_path), minify=minify)

        if vite_plugins:
            transformed_assets, vite_watch_files = transform_css_assets(
                vite_plugins,
                root=cwd,
                assets=[
                    {
                        "filename": page.page.css.as_posix(),
                        "path": str(synthetic_module_id),
                        "code": code,
                    },
                ],
            )
            watch_files.update(Path(path).resolve() for path in vite_watch_files)
            if transformed_assets:
                code = transformed_assets[0]["code"]

        if not code.endswith("\n"):
            code = f"{code}\n"
        css_output_path.write_text(code, encoding="utf-8")

    return watch_files


def _build_javascript(
    inputs: dict[str, str],
    *,
    cwd: Path,
    output_dir: Path,
    plugins: list[BundlerPlugin],
) -> None:
    if not inputs:
        return
    bundler = Bundler(
        cwd=cwd,
        plugins=plugins,
        output={
            "dir": str(output_dir),
            "format": "esm",
            "entry_file_names": "[name].js",
        },
    )
    with bundler() as build:
        build(inputs)


def _build_once(
    pages: list[Page],
    *,
    dev: bool,
    minify: bool,
    output: Path | None,
    cwd: Path | None,
    plugins: list[BundlerPlugin | VitePlugin] | None,
) -> set[Path]:
    del dev
    actual_cwd = cwd.resolve() if cwd is not None else Path.cwd().resolve()
    output_dir = _resolve_output_dir(output=output, cwd=actual_cwd)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_pages = _normalize_pages(
        pages,
        cwd=actual_cwd,
        output_dir=output_dir,
    )

    bundler_plugins: list[BundlerPlugin] = []
    css_plugins: list[BundlerPlugin] = []
    vite_plugins: list[VitePlugin] = []
    for plugin in plugins or []:
        if isinstance(plugin, VitePlugin):
            vite_plugins.append(plugin)
            continue
        if not isinstance(plugin, BundlerPlugin):
            msg = "Amber plugins must be gdansk_bundler.Plugin or VitePlugin instances"
            raise TypeError(msg)
        bundler_plugins.append(plugin)
        css_plugins.append(plugin)

    page_assets = {page.absolute_path: _collect_page_assets(page, root=actual_cwd) for page in normalized_pages}
    client_inputs, server_inputs = _prepare_entry_files(normalized_pages, output_dir=output_dir)

    js_plugins = [*bundler_plugins, _CssStubPlugin(root=actual_cwd)]
    _build_javascript(client_inputs, cwd=actual_cwd, output_dir=output_dir, plugins=js_plugins)
    _build_javascript(server_inputs, cwd=actual_cwd, output_dir=output_dir, plugins=js_plugins)

    watch_files = {path.resolve() for assets in page_assets.values() for path in assets.watch_paths}
    watch_files.update(
        _build_css_outputs(
            normalized_pages,
            page_assets,
            cwd=actual_cwd,
            output_dir=output_dir,
            minify=minify,
            css_plugins=css_plugins,
            vite_plugins=vite_plugins,
        ),
    )
    return watch_files


def _watch_state(paths: set[Path]) -> dict[Path, tuple[int, int] | None]:
    state: dict[Path, tuple[int, int] | None] = {}
    for path in paths:
        if not path.exists():
            state[path] = None
            continue
        stat = path.stat()
        state[path] = (stat.st_mtime_ns, stat.st_size)
    return state


def _watch_loop(
    *,
    pages: list[Page],
    minify: bool,
    output: Path | None,
    cwd: Path | None,
    plugins: list[BundlerPlugin | VitePlugin] | None,
    stop_event: threading.Event,
) -> None:
    watched_files = _build_once(
        pages,
        dev=True,
        minify=minify,
        output=output,
        cwd=cwd,
        plugins=plugins,
    )
    snapshot = _watch_state(watched_files)
    while not stop_event.wait(0.1):
        current = _watch_state(watched_files)
        if current == snapshot:
            continue
        watched_files = _build_once(
            pages,
            dev=True,
            minify=minify,
            output=output,
            cwd=cwd,
            plugins=plugins,
        )
        snapshot = _watch_state(watched_files)


async def bundle(
    pages: list[Page],
    dev: bool = False,
    minify: bool = True,
    output: Path | None = None,
    cwd: Path | None = None,
    plugins: list[BundlerPlugin | VitePlugin] | None = None,
) -> None:
    if not dev:
        _build_once(
            pages,
            dev=dev,
            minify=minify,
            output=output,
            cwd=cwd,
            plugins=plugins,
        )
        return

    _build_once(
        pages,
        dev=True,
        minify=minify,
        output=output,
        cwd=cwd,
        plugins=plugins,
    )
    stop_event = threading.Event()
    watch_thread = threading.Thread(
        target=_watch_loop,
        kwargs={
            "pages": pages,
            "minify": minify,
            "output": output,
            "cwd": cwd,
            "plugins": plugins,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    watch_thread.start()
    while True:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stop_event.set()
            watch_thread.join(timeout=5)
            raise


async def run(code: str) -> object:
    if _MODULE_SYNTAX_PATTERN.search(code):
        return await _run_module(code)
    return await _run_inline(code)


async def _run_inline(code: str) -> object:
    script = Script(
        f"""export default function() {{
  let gdanskHtml = null;
  globalThis.Deno ??= {{}};
  Deno.core ??= {{}};
  Deno.core.ops ??= {{}};
  Deno.core.ops.op_gdansk_set_html = (html) => {{
    gdanskHtml = html;
  }};
  const result = (0, eval)({json.dumps(code)});
  if (gdanskHtml !== null) {{
    return gdanskHtml;
  }}
  if (result && typeof result.then === "function") {{
    return Symbol.for("gdansk.unsupported_promise");
  }}
  return gdanskHtml ?? result;
}}""",
        type(None),
        object,
    )
    async with _RUNNER(script) as ctx:
        return await ctx(None)


async def _run_module(code: str) -> object:
    with tempfile.TemporaryDirectory(prefix="gdansk-runtime-", dir=Path.cwd()) as tmpdir:
        root = Path(tmpdir)
        source_path = root / "source.js"
        wrapper_path = root / _RUNTIME_ENTRY_PATH
        source_path.write_text(code, encoding="utf-8")
        wrapper_path.write_text(
            """export default async function() {
  let gdanskHtml = null;
  globalThis.Deno ??= {};
  Deno.core ??= {};
  Deno.core.ops ??= {};
  Deno.core.ops.op_gdansk_set_html = (html) => {
    gdanskHtml = html;
  };
  const mod = await import("./source.js");
  const result = await mod.default();
  return gdanskHtml ?? result;
}
""",
            encoding="utf-8",
        )
        script = Script.from_file(wrapper_path, type(None), object)
        async with _RUNNER(script) as ctx:
            return await ctx(None)
