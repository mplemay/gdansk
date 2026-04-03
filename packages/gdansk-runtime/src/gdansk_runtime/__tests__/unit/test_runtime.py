from __future__ import annotations

from os import PathLike

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
