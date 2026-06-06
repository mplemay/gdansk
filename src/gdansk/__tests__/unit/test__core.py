from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

import gdansk
from gdansk._core import (
    PackageInstallResult,
    PackageUpdateChange,
    PackageUpdateResult,
    Runtime,
    RuntimeOptions,
    Script,
    ainstall_packages,
    alock_packages,
    aupdate_packages,
    install_packages,
    lock_packages,
    update_packages,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def default_export_source() -> str:
    return """
export default function run(input) {
  return { ok: true, input };
}
"""


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


def test_runtime_api_is_exported_from_top_level_package():
    assert gdansk.Runtime is Runtime
    assert gdansk.RuntimeOptions is RuntimeOptions
    assert gdansk.Script is Script
    assert gdansk.PackageInstallResult is PackageInstallResult
    assert gdansk.PackageUpdateChange is PackageUpdateChange
    assert gdansk.PackageUpdateResult is PackageUpdateResult
    assert gdansk.install_packages is install_packages
    assert gdansk.lock_packages is lock_packages
    assert gdansk.update_packages is update_packages
    assert gdansk.ainstall_packages is ainstall_packages
    assert gdansk.alock_packages is alock_packages
    assert gdansk.aupdate_packages is aupdate_packages


def test_script_accepts_inline_javascript_and_typescript(default_export_source: str):
    assert isinstance(Script(default_export_source), Script)
    assert isinstance(Script("export default function run(input: { value: number }) { return input.value; }"), Script)


@pytest.mark.parametrize("source", [None, b"export default () => null;", 42, Path("script.js")])
def test_script_rejects_non_string_source(source: object):
    with pytest.raises(TypeError):
        Script(cast("Any", source))


def test_script_from_file_loads_pathlike_values(write_script: Callable[[str, str], Path]):
    path = write_script("export default function run() { return 'ok'; }", "scripts/main.ts")

    script = Script.from_file(path)

    assert isinstance(script, Script)
    assert "file script" in repr(script)


def test_script_from_file_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Script.from_file(tmp_path / "missing.ts")


def test_runtime_options_accept_supported_memory_fields():
    options = RuntimeOptions(
        max_old_generation_size_mb=64,
        max_young_generation_size_mb=16,
        code_range_size_mb=32,
    )

    assert "RuntimeOptions" in repr(options)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_old_generation_size_mb": 0},
        {"max_old_generation_size_mb": -1},
        {"max_young_generation_size_mb": 0},
        {"max_young_generation_size_mb": -1},
        {"code_range_size_mb": 0},
        {"code_range_size_mb": -1},
    ],
)
def test_runtime_options_reject_non_positive_memory_fields(kwargs: dict[str, int]):
    with pytest.raises(ValueError, match="positive"):
        RuntimeOptions(**kwargs)


def test_runtime_accepts_default_and_explicit_cwd(tmp_path: Path):
    assert isinstance(Runtime(), Runtime)
    assert isinstance(Runtime(cwd=tmp_path), Runtime)
    assert str(tmp_path) in repr(Runtime(cwd=tmp_path))


def test_runtime_rejects_invalid_cwd(tmp_path: Path):
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        Runtime(cwd=tmp_path / "missing")
    with pytest.raises(OSError, match="cwd is not a directory"):
        Runtime(cwd=file_path)
    with pytest.raises(TypeError):
        Runtime(cwd=cast("Any", object()))


def test_runtime_bind_returns_sync_and_async_context_managers(default_export_source: str, tmp_path: Path):
    bound_runtime = Runtime(cwd=tmp_path)(Script(default_export_source))

    assert hasattr(bound_runtime, "__enter__")
    assert hasattr(bound_runtime, "__exit__")
    assert hasattr(bound_runtime, "__aenter__")
    assert hasattr(bound_runtime, "__aexit__")


def test_runtime_enter_without_bound_script_raises_runtime_error(tmp_path: Path):
    with pytest.raises(RuntimeError, match="bound to a Script"), Runtime(cwd=tmp_path):
        pass


def test_package_helpers_require_gdansk_dependency_tables(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(Exception, match="No gdansk package dependencies"):
        install_packages(cwd=tmp_path)
    with pytest.raises(Exception, match="No gdansk package dependencies"):
        update_packages(cwd=tmp_path, packages=[])


def test_package_helpers_reject_non_string_dependency_entries(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[gdansk.dependencies]
react = ["^19"]
""",
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="must be a string dependency specifier"):
        install_packages(cwd=tmp_path)


def test_async_package_helpers_are_exported_and_validate_tables(tmp_path: Path):
    async def run_test() -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

        with pytest.raises(Exception, match="No gdansk package dependencies"):
            await ainstall_packages(cwd=tmp_path)
        with pytest.raises(Exception, match="No gdansk package dependencies"):
            await alock_packages(cwd=tmp_path)
        with pytest.raises(Exception, match="No gdansk package dependencies"):
            await aupdate_packages(cwd=tmp_path)

    asyncio.run(run_test())
