from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from gdansk_runtime import Runtime, Script

if TYPE_CHECKING:
    from pathlib import Path

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


def test_runtime_lock_then_sync_supports_linked_packages_with_peer_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    configure_npm_test_env(monkeypatch, tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shared_dir = project_dir / "shared"
    shared_dir.mkdir()
    (shared_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "@myorg/shared",
                "version": "1.0.0",
                "type": "module",
                "exports": "./index.js",
                "peerDependencies": {"zod": "^4.3.6"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (shared_dir / "index.js").write_text("export const shared = true;\n", encoding="utf-8")
    package_json = write_package_json(
        project_dir,
        {
            "@myorg/shared": "file:./shared",
            "zod": "4.3.6",
        },
    )

    Runtime(package_json=package_json).lock()

    lockfile = json.loads((project_dir / "deno.lock").read_text(encoding="utf-8"))
    assert "npm:zod@4.3.6" in lockfile["workspace"]["packageJson"]["dependencies"]

    Runtime(package_json=package_json).sync()

    assert (project_dir / "node_modules" / "@myorg" / "shared" / "package.json").exists()
    assert read_installed_package_version(project_dir, "@myorg/shared") == "1.0.0"
    assert read_installed_package_version(project_dir, "zod") == "4.3.6"


def test_runtime_sync_allows_bare_package_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    configure_npm_test_env(monkeypatch, tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shared_dir = project_dir / "shared"
    shared_dir.mkdir()
    (shared_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "sample-package",
                "version": "1.0.0",
                "type": "module",
                "exports": "./index.js",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (shared_dir / "index.js").write_text(
        "export default { greet(value) { return `hello ${value}`; } };\n",
        encoding="utf-8",
    )
    package_json = write_package_json(project_dir, {"sample-package": "file:./shared"})
    runtime = Runtime(package_json=package_json)
    runtime.sync()

    script = Script(
        contents="""
import samplePackage from "sample-package";

export default function(input) {
    return samplePackage.greet(input);
}
""".strip(),
        inputs=str,
        outputs=str,
    )

    with runtime(script) as run:
        assert run("gdansk") == "hello gdansk"


async def test_async_runtime_sync_allows_bare_package_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    configure_npm_test_env(monkeypatch, tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shared_dir = project_dir / "shared"
    shared_dir.mkdir()
    (shared_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "sample-package",
                "version": "1.0.0",
                "type": "module",
                "exports": "./index.js",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (shared_dir / "index.js").write_text(
        "export default { greet(value) { return `hello ${value}`; } };\n",
        encoding="utf-8",
    )
    package_json = write_package_json(project_dir, {"sample-package": "file:./shared"})
    runtime = Runtime(package_json=package_json)
    runtime.sync()

    script = Script(
        contents="""
import samplePackage from "sample-package";

export default function(input) {
    return samplePackage.greet(input);
}
""".strip(),
        inputs=str,
        outputs=str,
    )

    async with runtime(script) as run:
        assert await run("gdansk") == "hello gdansk"
