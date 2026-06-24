from __future__ import annotations

from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject
from gdansk._project import read_pyproject_document


def test_init_creates_scaffold_and_gdansk_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    calls: list[Path] = []

    def fake_lock_project(project) -> SimpleNamespace:
        calls.append(project.root)
        return SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=6)

    monkeypatch.setattr("gdansk.cli.lock_project", fake_lock_project)

    code, stdout, _stderr = run_cli(
        ["init", "--path", str(target)],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    assert calls == [target.resolve()]
    assert (target / "src" / "my_mcp_server" / "__main__.py").exists()
    assert (target / "src" / "my_mcp_server" / "views" / "vite.config.ts").exists()
    assert (target / "src" / "my_mcp_server" / "views" / "widgets" / "hello" / "widget.tsx").exists()
    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "[gdansk.dependencies]" in text
    assert "[gdansk.dependencies.dev]" in text
    assert "[gdansk.commands]" not in text
    assert "[belgie" not in text
    assert "Initialized gdansk project" in stdout


def test_init_no_lock_skips_locking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"

    def fail_lock_project(_project) -> SimpleNamespace:
        msg = "lock should not run"
        raise AssertionError(msg)

    monkeypatch.setattr("gdansk.cli.lock_project", fail_lock_project)

    code, _stdout, _stderr = run_cli(
        ["init", "--path", str(target), "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0


def test_init_appends_gdansk_to_existing_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        '[project]\nname = "existing"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    run_cli(
        ["init", "--path", str(target), "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    document = read_pyproject_document(target)
    assert document["project"]["name"] == "existing"
    assert "dependencies" in document["gdansk"]
    assert (target / "src" / "existing" / "views" / "vite.config.ts").exists()


def test_init_refuses_existing_gdansk_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    target.mkdir()
    write_pyproject(target)

    code, _stdout, stderr = run_cli(
        ["init", "--path", str(target), "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 1
    assert "already present" in stderr


def test_init_force_replaces_legacy_belgie_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        """
[project]
name = "existing"
version = "0.1.0"

[belgie.dependencies]
old = "1"
""",
        encoding="utf-8",
    )

    run_cli(
        ["init", "--path", str(target), "--force", "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "[belgie" not in text
    assert "[gdansk.dependencies]" in text
    assert "old" not in text


def test_init_custom_package_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"

    run_cli(
        ["init", "--path", str(target), "--package", "custom_pkg", "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    document = read_pyproject_document(target)
    assert document["project"]["scripts"]["main"] == "custom_pkg.__main__:main"
    assert (target / "src" / "custom_pkg" / "views" / "vite.config.ts").exists()


def test_init_refuses_existing_main_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    main_path = target / "src" / "my_mcp_server" / "__main__.py"
    main_path.parent.mkdir(parents=True)
    main_path.write_text("def main(): pass\n", encoding="utf-8")

    code, _stdout, stderr = run_cli(
        ["init", "--path", str(target), "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 1
    assert "Refusing to overwrite existing entrypoint" in stderr


def test_init_refuses_non_empty_views_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    views_path = target / "src" / "my_mcp_server" / "views"
    views_path.mkdir(parents=True)
    (views_path / "existing.txt").write_text("keep\n", encoding="utf-8")

    code, _stdout, stderr = run_cli(
        ["init", "--path", str(target), "--no-lock"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 1
    assert "Refusing to scaffold into non-empty views directory" in stderr


def test_templates_are_loadable():
    names = {item.name for item in resources.files("gdansk.cli.templates").iterdir()}
    assert {
        "__main__.py",
        "__init__.py",
        "vite.config.ts",
        "widget.tsx",
        "pyproject.toml",
        "gdansk_tables.toml",
    } <= names
