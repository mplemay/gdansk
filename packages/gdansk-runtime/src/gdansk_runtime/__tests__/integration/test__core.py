from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gdansk_runtime import Runtime

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("GDANSK_RUNTIME_NPM_INTEGRATION") != "1",
        reason="Set GDANSK_RUNTIME_NPM_INTEGRATION=1 to run npm integration tests.",
    ),
]


def write_package_json(project_dir: Path, dependencies: dict[str, str]) -> Path:
    package_json = project_dir / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "name": "gdansk-runtime-test",
                "private": True,
                "dependencies": dependencies,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return package_json


def read_installed_package_version(project_dir: Path, package_name: str) -> str:
    package_json = project_dir / "node_modules" / package_name / "package.json"
    return json.loads(package_json.read_text(encoding="utf-8"))["version"]


def configure_npm_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("DENO_DIR", str(tmp_path / "deno-dir"))


def test_runtime_lock_writes_deno_lock_without_node_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    configure_npm_test_env(monkeypatch, tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    package_json = write_package_json(project_dir, {"picocolors": "^1.1.1"})

    Runtime(package_json=package_json).lock()

    assert (project_dir / "deno.lock").exists()
    assert not (project_dir / "node_modules").exists()


def test_runtime_sync_installs_node_modules_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    configure_npm_test_env(monkeypatch, tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    package_json = write_package_json(project_dir, {"picocolors": "^1.1.1"})
    runtime = Runtime(package_json=package_json)

    runtime.sync()

    lockfile = project_dir / "deno.lock"
    node_modules = project_dir / "node_modules"
    first_lockfile = lockfile.read_text(encoding="utf-8")
    first_version = read_installed_package_version(project_dir, "picocolors")

    runtime.sync()

    assert node_modules.exists()
    assert (node_modules / "picocolors" / "package.json").exists()
    assert lockfile.read_text(encoding="utf-8") == first_lockfile
    assert read_installed_package_version(project_dir, "picocolors") == first_version


def test_runtime_sync_updates_lockfile_and_installed_packages_after_package_json_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    configure_npm_test_env(monkeypatch, tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    package_json = write_package_json(project_dir, {"picocolors": "^1.1.1"})
    runtime = Runtime(package_json=package_json)

    runtime.sync()
    first_lockfile = (project_dir / "deno.lock").read_text(encoding="utf-8")

    write_package_json(project_dir, {"kleur": "^4.1.5"})
    runtime.sync()

    assert (project_dir / "node_modules" / "kleur" / "package.json").exists()
    assert not (project_dir / "node_modules" / "picocolors").exists()
    assert (project_dir / "deno.lock").read_text(encoding="utf-8") != first_lockfile
    assert read_installed_package_version(project_dir, "kleur") == "4.1.5"
