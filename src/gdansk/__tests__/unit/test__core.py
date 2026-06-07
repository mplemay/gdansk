from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, cast

import pytest

import gdansk
from gdansk import (
    GdanskError,
    GdanskJavaScriptError,
    GdanskModuleError,
    GdanskRuntimeError,
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
    from pathlib import Path


def test_runtime_api_is_exported_from_top_level_gdansk() -> None:
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


def test_gdansk_exception_hierarchy_is_exported() -> None:
    assert issubclass(GdanskRuntimeError, GdanskError)
    assert issubclass(GdanskModuleError, GdanskError)
    assert issubclass(GdanskJavaScriptError, GdanskError)


def test_runtime_options_accept_memory_limits() -> None:
    options = RuntimeOptions(max_old_generation_size_mb=64, max_young_generation_size_mb=16, code_range_size_mb=32)

    assert isinstance(options, RuntimeOptions)
    assert "RuntimeOptions" in repr(options)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_old_generation_size_mb": 0},
        {"max_young_generation_size_mb": -1},
        {"code_range_size_mb": 0},
    ],
)
def test_runtime_options_reject_non_positive_memory_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="positive"):
        RuntimeOptions(**kwargs)


def test_script_accepts_inline_source(default_export_source: str) -> None:
    script = Script(default_export_source)

    assert isinstance(script, Script)
    assert "Script" in repr(script)


def test_script_loads_from_file(write_script: Callable[[str, str], Path], named_run_source: str) -> None:
    path = write_script(named_run_source, "main.ts")

    script = Script.from_file(path)

    assert isinstance(script, Script)


def test_runtime_executes_sync_script(tmp_path: Path) -> None:
    runtime = Runtime(cwd=tmp_path)
    script = Script("export default function run(input) { return { value: input.value + 1 }; }")

    with runtime(script) as run:
        assert run({"value": 41}) == {"value": 42}


async def test_runtime_executes_async_script(tmp_path: Path) -> None:
    runtime = Runtime(cwd=tmp_path)
    script = Script("export default async function run(input) { return await Promise.resolve(input.items); }")

    async with runtime(script) as run:
        result = run({"items": [1, 2, 3]})
        assert inspect.isawaitable(result)
        assert await result == [1, 2, 3]


def test_runtime_round_trips_json_values(tmp_path: Path) -> None:
    value = {
        "none": None,
        "bool": True,
        "int": 42,
        "float": 3.5,
        "string": "gdansk",
        "array": [1, "two", None],
        "object": {"nested": True},
        "tuple": (1, 2),
    }

    with Runtime(cwd=tmp_path)(Script("export default function run(input) { return input; }")) as run:
        assert run(value) == {**value, "tuple": [1, 2]}


def test_missing_run_export_raises_gdansk_module_error(tmp_path: Path) -> None:
    with (
        pytest.raises(GdanskModuleError, match="run"),
        Runtime(cwd=tmp_path)(
            Script("export const answer = 42;"),
        ) as run,
    ):
        run()


def test_javascript_error_raises_gdansk_javascript_error(tmp_path: Path) -> None:
    script = Script('export default function run() { throw new Error("boom"); }')

    with pytest.raises(GdanskJavaScriptError, match="boom"), Runtime(cwd=tmp_path)(script) as run:
        run()


def test_closed_runner_raises_gdansk_runtime_error(tmp_path: Path) -> None:
    with Runtime(cwd=tmp_path)(Script("export default function run() { return 'ok'; }")) as run:
        assert run() == "ok"

    with pytest.raises(GdanskRuntimeError, match="closed"):
        run()


def test_runtime_rejects_non_runtime_options(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        Runtime(cwd=tmp_path, options=cast("Any", object()))


def test_package_helpers_require_gdansk_dependency_tables(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(GdanskRuntimeError, match="No gdansk package dependencies"):
        install_packages(cwd=tmp_path)


async def test_async_package_helpers_are_exported_and_renamed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(GdanskRuntimeError, match="No gdansk package dependencies"):
        await ainstall_packages(cwd=tmp_path)
    with pytest.raises(GdanskRuntimeError, match="No gdansk package dependencies"):
        await alock_packages(cwd=tmp_path)
    with pytest.raises(GdanskRuntimeError, match="No gdansk package dependencies"):
        await aupdate_packages(cwd=tmp_path)


def test_package_helpers_read_gdansk_dependency_table_errors(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[gdansk.dependencies]
react = ["^19"]
""",
        encoding="utf-8",
    )

    with pytest.raises(GdanskRuntimeError, match=r"\[gdansk\.dependencies\].*string dependency specifier"):
        lock_packages(cwd=tmp_path)


def test_package_update_accepts_empty_filter_but_requires_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(GdanskRuntimeError, match="No gdansk package dependencies"):
        update_packages(cwd=tmp_path, packages=[])


def test_no_deno_public_error_names_are_exported() -> None:
    assert not hasattr(gdansk, "DenoError")
    assert not hasattr(gdansk, "DenoRuntimeError")
