from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gdansk_lightningcss._core import transform_css

__all__ = ["CssBundleResult", "bundle_css_paths", "expand_css_imports", "resolve_css_import_path"]

_CSS_IMPORT_PATTERN = re.compile(
    r"""@import\s+(?:url\s*\(\s*['"]?([^'")]+)['"]?\s*\)|['"]([^'"]+)['"])\s*([^;]*);""",
)


@dataclass(frozen=True, slots=True)
class CssBundleResult:
    code: str
    files: tuple[Path, ...]


def _split_package_specifier(specifier: str) -> tuple[str, str | None] | None:
    if specifier.startswith(("./", "../")) or Path(specifier).is_absolute():
        return None

    if specifier.startswith("@"):
        remainder = specifier.removeprefix("@")
        if "/" not in remainder:
            return None
        scope, tail = remainder.split("/", 1)
        if "/" in tail:
            name, subpath = tail.split("/", 1)
            return f"@{scope}/{name}", subpath
        return f"@{scope}/{tail}", None

    if "/" in specifier:
        package_name, subpath = specifier.split("/", 1)
        return package_name, subpath
    return specifier, None


def _find_node_modules_package_dir(package_name: str, importer_dir: Path, root: Path) -> Path | None:
    current = importer_dir
    while True:
        candidate = current / "node_modules" / package_name
        if candidate.is_dir():
            return candidate.resolve()
        if current == root:
            return None
        if not current.is_relative_to(root):
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _extract_style_export_target(entry: object, specifier: str, export_key: str) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        style = cast("dict[str, object]", entry).get("style")
        if isinstance(style, str):
            return style
        msg = f'package "{specifier}" does not define exports["{export_key}"].style'
        raise ValueError(msg)
    msg = f'package "{specifier}" has an unsupported exports["{export_key}"] value'
    raise ValueError(msg)


def _resolve_package_style_export(package_dir: Path, specifier: str, subpath: str | None) -> Path:
    package_json_path = package_dir / "package.json"
    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    export_key = f"./{subpath}" if subpath else "."
    exports = package_json.get("exports", {})
    if export_key not in exports:
        msg = f'package "{specifier}" does not define exports["{export_key}"]'
        raise ValueError(msg)
    style_target = _extract_style_export_target(exports[export_key], specifier, export_key)
    return (package_dir / style_target).resolve()


def resolve_css_import_path(specifier: str, importer_dir: Path, root: Path) -> Path:
    if specifier.startswith(("./", "../")):
        path = (importer_dir / specifier).resolve()
    elif Path(specifier).is_absolute():
        path = Path(specifier).resolve()
    else:
        split = _split_package_specifier(specifier)
        if split is None:
            msg = f'failed to resolve css import "{specifier}"'
            raise ValueError(msg)
        package_name, subpath = split
        package_dir = _find_node_modules_package_dir(package_name, importer_dir, root)
        if package_dir is None:
            msg = f'failed to resolve css import "{specifier}"'
            raise ValueError(msg)
        if subpath is not None:
            candidate = package_dir / subpath
            if candidate.exists():
                path = candidate.resolve()
            else:
                path = _resolve_package_style_export(package_dir, specifier, subpath)
        else:
            path = _resolve_package_style_export(package_dir, specifier, None)

    if not path.exists() or not path.is_file():
        msg = f'failed to resolve css import "{specifier}"'
        raise ValueError(msg)
    return path


def _wrap_import_conditions(expanded: str, conditions: str) -> str:
    normalized = conditions.strip()
    if not normalized:
        return expanded
    return f"@media {normalized} {{\n{expanded}\n}}\n"


def expand_css_imports(
    code: str,
    *,
    importer_dir: Path,
    root: Path,
    preserve_specifiers: frozenset[str] = frozenset(),
    _stack: tuple[Path, ...] = (),
) -> CssBundleResult:
    watched: set[Path] = set()
    parts: list[str] = []
    last_end = 0

    for match in _CSS_IMPORT_PATTERN.finditer(code):
        parts.append(code[last_end : match.start()])
        specifier = match.group(1) or match.group(2) or ""
        conditions = match.group(3).strip()
        if specifier in preserve_specifiers:
            parts.append(match.group(0))
            last_end = match.end()
            continue

        path = resolve_css_import_path(specifier, importer_dir, root)
        watched.add(path)
        if path in _stack:
            parts.append(f"/* circular @import skipped: {specifier} */\n")
            last_end = match.end()
            continue

        nested = expand_css_imports(
            path.read_text(encoding="utf-8"),
            importer_dir=path.parent,
            root=root,
            preserve_specifiers=preserve_specifiers,
            _stack=(*_stack, path),
        )
        watched.update(nested.files)
        parts.append(_wrap_import_conditions(nested.code, conditions))
        last_end = match.end()

    parts.append(code[last_end:])
    return CssBundleResult("".join(parts), tuple(sorted(watched)))


def _synthetic_import_specifier(path: Path, *, module_dir: Path) -> str:
    resolved_path = path.resolve()
    resolved_module_dir = module_dir.resolve()
    try:
        value = resolved_path.relative_to(resolved_module_dir).as_posix()
    except ValueError:
        value = Path(os.path.relpath(resolved_path, resolved_module_dir)).as_posix()
    if not value.startswith((".", "/")):
        return f"./{value}"
    return value


def bundle_css_paths(
    paths: list[Path],
    *,
    root: Path,
    module_id: Path,
    minify: bool,
    preserve_specifiers: frozenset[str] = frozenset(),
    finalize: bool = True,
) -> CssBundleResult:
    module_dir = module_id.parent
    watched = {path.resolve() for path in paths}
    source = "".join(
        f'@import "{_synthetic_import_specifier(path.resolve(), module_dir=module_dir)}";\n' for path in paths
    )
    expanded = expand_css_imports(
        source,
        importer_dir=module_dir,
        root=root.resolve(),
        preserve_specifiers=preserve_specifiers,
    )
    watched.update(expanded.files)
    code = expanded.code
    if finalize:
        code = transform_css(code, str(module_id), minify=minify)
        if not code.endswith("\n"):
            code = f"{code}\n"
    return CssBundleResult(code=code, files=tuple(sorted(watched)))
