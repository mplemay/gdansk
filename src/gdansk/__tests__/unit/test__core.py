from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

core_impl = importlib.import_module("gdansk._core")
run_inline_impl: Any = getattr(core_impl, "_run_inline", None)
run_module_impl: Any = getattr(core_impl, "_run_module", None)
runtime_inline_wrapper_path: Any = getattr(core_impl, "_RUNTIME_INLINE_WRAPPER_PATH", None)
runtime_module_wrapper_path: Any = getattr(core_impl, "_RUNTIME_MODULE_WRAPPER_PATH", None)
if run_inline_impl is None:
    msg = "expected gdansk._core._run_inline"
    raise RuntimeError(msg)
if run_module_impl is None:
    msg = "expected gdansk._core._run_module"
    raise RuntimeError(msg)
if runtime_inline_wrapper_path is None:
    msg = "expected gdansk._core._RUNTIME_INLINE_WRAPPER_PATH"
    raise RuntimeError(msg)
if runtime_module_wrapper_path is None:
    msg = "expected gdansk._core._RUNTIME_MODULE_WRAPPER_PATH"
    raise RuntimeError(msg)


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.script: object | None = None

    def __call__(self, script: object) -> _FakeRunner:
        self.script = script
        return self

    async def __aenter__(self) -> object:
        async def _ctx(value: object) -> str:
            self.calls.append(value)
            return "ok"

        return _ctx

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


async def test_run_inline_uses_checked_in_wrapper_file() -> None:
    runner = _FakeRunner()
    fake_script = object()

    with (
        patch("gdansk._core.Script.from_file", return_value=fake_script) as mock_from_file,
        patch("gdansk._core._RUNNER", runner),
    ):
        result = await run_inline_impl("1 + 1")

    assert result == "ok"
    assert runner.script is fake_script
    assert runner.calls == [{"code": "1 + 1"}]
    mock_from_file.assert_called_once_with(runtime_inline_wrapper_path, dict[str, str], object)


async def test_run_module_uses_system_tempdir_and_checked_in_wrapper_file(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    fake_script = object()
    runner = _FakeRunner()

    class _FakeTemporaryDirectory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["args"] = args
            captured["kwargs"] = kwargs

        def __enter__(self) -> str:
            return str(tmp_path)

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            return None

    with (
        patch("gdansk._core.tempfile.TemporaryDirectory", _FakeTemporaryDirectory),
        patch("gdansk._core.Script.from_file", return_value=fake_script) as mock_from_file,
        patch("gdansk._core._RUNNER", runner),
    ):
        result = await run_module_impl("export default function() { return 1; }\n")

    source_path = tmp_path / "source.js"
    assert result == "ok"
    assert captured["args"] == ()
    assert captured["kwargs"] == {"prefix": "gdansk-runtime-"}
    assert "return 1" in source_path.read_text(encoding="utf-8")
    assert runner.script is fake_script
    assert runner.calls == [{"sourcePath": source_path.resolve().as_uri()}]
    mock_from_file.assert_called_once_with(runtime_module_wrapper_path, dict[str, str], object)
