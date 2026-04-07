from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def read_package_json(package_dir: Path) -> dict[str, Any]:
    path = package_dir / "package.json"
    return json.loads(path.read_text(encoding="utf-8"))


def package_main_file(package_dir: Path, package_json: dict[str, Any]) -> Path:
    exported = package_json.get("exports", {}).get(".")
    if isinstance(exported, str):
        return (package_dir / exported).resolve()
    if isinstance(exported, dict):
        for key in ("import", "default"):
            v = exported.get(key)
            if isinstance(v, str):
                return (package_dir / v).resolve()
    module = package_json.get("module")
    if isinstance(module, str):
        return (package_dir / module).resolve()
    main = package_json.get("main")
    if isinstance(main, str):
        return (package_dir / main).resolve()
    return (package_dir / "index.js").resolve()


def resolve_package_entry(root: Path, package_name: str) -> Path:
    package_dirs: list[Path] = []
    if package_name == "tailwindcss":
        package_dirs.append(root / "node_modules" / "tailwindcss")
        package_dirs.append(
            root / "node_modules" / "@tailwindcss" / "vite" / "node_modules" / "tailwindcss",
        )
    else:
        package_dirs.append(root.joinpath("node_modules", *package_name.split("/")))

    last_err: OSError | ValueError | KeyError | TypeError | json.JSONDecodeError | None = None
    for package_dir in package_dirs:
        try:
            package_json = read_package_json(package_dir)
            return package_main_file(package_dir, package_json)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as err:
            last_err = err
            continue

    msg = f"Cannot find module '{package_name}' under {root}"
    if last_err is not None:
        raise FileNotFoundError(msg) from last_err
    raise FileNotFoundError(msg)


def resolve_tailwind_module_file(root: Path) -> Path:
    path = resolve_package_entry(root, "tailwindcss")
    if not path.is_file():
        msg = f"tailwindcss entry is not a file: {path}"
        raise FileNotFoundError(msg)
    return path
