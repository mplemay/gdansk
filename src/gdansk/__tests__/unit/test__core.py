from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import patch

core_impl = importlib.import_module("gdansk._core")
run_module_impl: Any = getattr(core_impl, "_run_module", None)
if run_module_impl is None:
    msg = "expected gdansk._core._run_module"
    raise RuntimeError(msg)


class _FakeRunner:
    def __call__(self, script: object) -> _FakeRunner:
        self.script = script
        return self

    async def __aenter__(self) -> object:
        async def _ctx(_value: None) -> str:
            return "ok"

        return _ctx

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


async def test_run_module_uses_system_tempdir(tmp_path):
    captured: dict[str, object] = {}
    fake_script = object()

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
        patch("gdansk._core._RUNNER", _FakeRunner()),
    ):
        result = await run_module_impl("export default function() { return 1; }\n")

    source_path = tmp_path / "source.js"
    wrapper_path = tmp_path / "__gdansk_runtime_eval__.js"
    assert result == "ok"
    assert captured["args"] == ()
    assert captured["kwargs"] == {"prefix": "gdansk-runtime-"}
    assert "return 1" in source_path.read_text(encoding="utf-8")
    assert 'await import("./source.js")' in wrapper_path.read_text(encoding="utf-8")
    mock_from_file.assert_called_once_with(wrapper_path, type(None), object)
