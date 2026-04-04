from __future__ import annotations

import tomllib
from os import PathLike
from pathlib import Path

from gdansk_runtime import Runtime
from gdansk_runtime._core import Runtime as RuntimeImpl


class _PackageJsonPath(PathLike[str]):
    def __init__(self, path: str) -> None:
        self._path = path

    def __fspath__(self) -> str:
        return self._path


def test_public_runtime_wraps_core_runtime(tmp_path):
    package_json = tmp_path / "package.json"

    runtime = Runtime(package_json=package_json)

    assert isinstance(runtime, RuntimeImpl)


def test_runtime_accepts_python_pathlike_package_json(tmp_path):
    package_json = tmp_path / "package.json"

    runtime = Runtime(package_json=_PackageJsonPath(str(package_json)))

    assert isinstance(runtime, RuntimeImpl)


def test_runtime_package_does_not_advertise_a_console_script():
    pyproject = Path(__file__).resolve().parents[4] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]

    assert "scripts" not in project
