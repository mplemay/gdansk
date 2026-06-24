from __future__ import annotations

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.cli.shared.errors import eprint, runtime_errors


def _raise_runtime_failure() -> None:
    msg = "runtime failed"
    raise BelgieRuntimeError(msg)


def test_eprint_writes_to_stderr(capsys: pytest.CaptureFixture[str]):
    eprint("hello stderr")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "hello stderr\n"


def test_runtime_errors_maps_belgie_runtime_error_to_exit_1(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc, runtime_errors():
        _raise_runtime_failure()

    assert exc.value.code == 1
    assert "runtime failed" in capsys.readouterr().err
