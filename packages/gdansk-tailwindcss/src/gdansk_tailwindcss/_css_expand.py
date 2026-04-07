from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CSS_IMPORT = re.compile(
    r"@import\s+(?:url\s*\(\s*['\"]?([^'\"\)]+)['\"]?\s*\)|['\"]([^'\"]+)['\"])\s*;",
    re.IGNORECASE | re.MULTILINE,
)


def _is_relative_specifier(specifier: str) -> bool:
    return specifier.startswith(("./", "../"))


def split_package_specifier(specifier: str) -> tuple[str, str | None] | None:  # noqa: PLR0911
    if _is_relative_specifier(specifier):
        return None
    p = Path(specifier)
    if p.is_absolute():
        return None
    if specifier.startswith("@"):
        rest = specifier[1:]
        slash = rest.find("/")
        if slash == -1:
            return None
        scope = rest[:slash]
        rest2 = rest[slash + 1 :]
        slash2 = rest2.find("/")
        if slash2 == -1:
            return f"@{scope}/{rest2}", None
        return f"@{scope}/{rest2[:slash2]}", rest2[slash2 + 1 :]
    slash = specifier.find("/")
    if slash == -1:
        return specifier, None
    return specifier[:slash], specifier[slash + 1 :]


def find_node_modules_package_dir(package_name: str, importer_dir: Path, root: Path) -> Path | None:
    current = importer_dir.resolve()
    root = root.resolve()
    while True:
        candidate = current / "node_modules" / package_name
        if candidate.is_dir():
            return candidate
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _resolve_package_style_export(package_dir: Path, specifier: str, subpath: str | None) -> Path:
    package_json_path = package_dir / "package.json"
    package_json: dict[str, Any] = json.loads(package_json_path.read_text(encoding="utf-8"))
    export_key = f"./{subpath}" if subpath else "."
    exports = package_json.get("exports")
    if not isinstance(exports, dict):
        msg = f'package "{specifier}" has no exports map'
        raise TypeError(msg)
    export_entry = exports.get(export_key)
    if export_entry is None:
        msg = f'package "{specifier}" does not define exports["{export_key}"]'
        raise ValueError(msg)

    style_path: str | None = None
    if isinstance(export_entry, str):
        style_path = export_entry
    elif isinstance(export_entry, dict):
        raw_style = export_entry.get("style")
        if isinstance(raw_style, str):
            style_path = raw_style
        else:
            pkg_style = package_json.get("style")
            if isinstance(pkg_style, str):
                style_path = pkg_style
    if style_path is None:
        msg = f'package "{specifier}" does not define a style export for "{export_key}"'
        raise ValueError(msg)

    out = (package_dir / style_path).resolve()
    if not out.is_file():
        msg = f"resolved style file missing: {out}"
        raise FileNotFoundError(msg)
    return out


def resolve_css_import_path(specifier: str, importer_dir: Path, root: Path) -> Path:
    importer_dir = importer_dir.resolve()
    root = root.resolve()

    if _is_relative_specifier(specifier):
        out = (importer_dir / specifier).resolve()
        if not out.is_file():
            msg = f"CSS import not found: {specifier} (from {importer_dir})"
            raise FileNotFoundError(msg)
        return out

    p = Path(specifier)
    if p.is_absolute():
        out = p.resolve()
        if not out.is_file():
            msg = f"CSS import not found: {out}"
            raise FileNotFoundError(msg)
        return out

    parts = split_package_specifier(specifier)
    if parts is None:
        msg = f'failed to resolve css import "{specifier}"'
        raise ValueError(msg)
    package_name, subpath = parts
    package_dir = find_node_modules_package_dir(package_name, importer_dir, root)
    if package_dir is None:
        msg = f'failed to resolve css import "{specifier}"'
        raise FileNotFoundError(msg)

    if subpath:
        candidate = (package_dir / subpath).resolve()
        if candidate.is_file():
            return candidate

    return _resolve_package_style_export(package_dir, specifier, subpath)


def expand_css_imports(css: str, importer_dir: Path, root: Path) -> str:
    stack: list[Path] = []

    def expand_recursive(text: str, imp_dir: Path) -> str:
        out: list[str] = []
        pos = 0
        while True:
            match = _CSS_IMPORT.search(text, pos)
            if match is None:
                out.append(text[pos:])
                return "".join(out)
            out.append(text[pos : match.start()])
            spec = (match.group(1) or match.group(2) or "").strip()
            if not spec:
                out.append(match.group(0))
                pos = match.end()
                continue
            try:
                resolved = resolve_css_import_path(spec, imp_dir, root)
            except (OSError, ValueError) as err:
                msg = f'failed to resolve @import "{spec}": {err}'
                raise RuntimeError(msg) from err

            if resolved in stack:
                out.append(f"/* circular @import skipped: {resolved} */")
                pos = match.end()
                continue

            stack.append(resolved)
            try:
                inner = resolved.read_text(encoding="utf-8")
                inner_expanded = expand_recursive(inner, resolved.parent)
            finally:
                stack.pop()
            out.append(inner_expanded)
            pos = match.end()

    return expand_recursive(css, importer_dir)


def importer_dir_for_module(module_id: str, root: Path) -> Path:
    raw = Path(module_id)
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if path.is_dir():
        return path
    if path.suffix:
        return path.parent
    return path
