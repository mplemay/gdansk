from __future__ import annotations

from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest

from gdansk.__tests__.conftest import write_pyproject
from gdansk.cli import main


def _run_init(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    monkeypatch.chdir(cwd)
    exit_code = 0
    try:
        main(argv)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_init_creates_scaffold_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    monkeypatch.setattr(
        "gdansk.cli.lock_packages",
        lambda **_kwargs: SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0),
    )

    code, stdout, _stderr = _run_init(
        ["init", "--path", str(target), "--no-install"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    assert (target / "pyproject.toml").exists()
    assert (target / "src" / "my_mcp_server" / "__main__.py").exists()
    assert (target / "src" / "my_mcp_server" / "views" / "package.json").exists()
    assert (target / "src" / "my_mcp_server" / "views" / "vite.config.ts").exists()
    assert (target / "src" / "my_mcp_server" / "views" / "widgets" / "hello" / "widget.tsx").exists()
    assert "Initialized gdansk project" in stdout


def test_init_pyproject_contains_belgie_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    monkeypatch.setattr(
        "gdansk.cli.lock_packages",
        lambda **_kwargs: SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0),
    )

    _run_init(["init", "--path", str(target), "--no-install"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project]" in text
    assert 'main = "my_mcp_server.__main__:main"' in text
    assert "frontend =" not in text
    assert "[belgie.dependencies]" in text
    assert "[belgie.scripts]" in text


def test_init_main_uses_views_sibling_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    monkeypatch.setattr(
        "gdansk.cli.lock_packages",
        lambda **_kwargs: SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0),
    )

    _run_init(["init", "--path", str(target), "--no-install"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    text = (target / "src" / "my_mcp_server" / "__main__.py").read_text(encoding="utf-8")
    assert 'Path(__file__).parent / "views"' in text


def test_init_appends_belgie_to_existing_pyproject(
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
    monkeypatch.setattr(
        "gdansk.cli.lock_packages",
        lambda **_kwargs: SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0),
    )

    _run_init(["init", "--path", str(target), "--no-install"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "existing"' in text
    assert "[belgie.dependencies]" in text
    assert (target / "src" / "existing" / "views" / "vite.config.ts").exists()


def test_init_refuses_existing_belgie_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    target.mkdir()
    write_pyproject(target)

    code, _stdout, stderr = _run_init(
        ["init", "--path", str(target), "--no-install"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 1
    assert "already present" in stderr


def test_init_force_replaces_belgie_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    target.mkdir()
    write_pyproject(target, dependencies={"old": "1.0.0"})
    monkeypatch.setattr(
        "gdansk.cli.lock_packages",
        lambda **_kwargs: SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0),
    )

    _run_init(
        ["init", "--path", str(target), "--force", "--no-install"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "frontend =" not in text
    assert '"old"' not in text
    assert 'name = "example"' in text


def test_init_refuses_existing_main_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "existing"
    target.mkdir()
    main_path = target / "src" / "my_mcp_server" / "__main__.py"
    main_path.parent.mkdir(parents=True)
    main_path.write_text("print('main')\n", encoding="utf-8")

    code, _stdout, stderr = _run_init(
        ["init", "--path", str(target), "--no-install"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 1
    assert "__main__.py" in stderr


def test_init_runs_lock_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    calls: list[Path] = []

    def fake_lock_packages(**kwargs: object) -> SimpleNamespace:
        calls.append(Path(str(kwargs["cwd"])))
        return SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0)

    monkeypatch.setattr("gdansk.cli.lock_packages", fake_lock_packages)

    _run_init(["init", "--path", str(target)], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert calls == [target.resolve()]


def test_init_no_install_skips_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"

    def fail_lock_packages(**_kwargs: object) -> SimpleNamespace:
        msg = "lock should not run"
        raise AssertionError(msg)

    monkeypatch.setattr("gdansk.cli.lock_packages", fail_lock_packages)

    _run_init(["init", "--path", str(target), "--no-install"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)


def test_init_custom_package_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    monkeypatch.setattr(
        "gdansk.cli.lock_packages",
        lambda **_kwargs: SimpleNamespace(lockfile=str(target / "deno.lock"), dependencies=4, dev_dependencies=0),
    )

    _run_init(
        ["init", "--path", str(target), "--package", "custom_pkg", "--no-install"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'main = "custom_pkg.__main__:main"' in text
    assert (target / "src" / "custom_pkg" / "views" / "vite.config.ts").exists()


def test_templates_are_loadable():
    names = {item.name for item in resources.files("gdansk._cli_templates").iterdir()}
    assert {
        "__main__.py",
        "__init__.py",
        "package.json",
        "vite.config.ts",
        "widget.tsx",
        "pyproject.toml",
        "belgie_tables.toml",
    } <= names
