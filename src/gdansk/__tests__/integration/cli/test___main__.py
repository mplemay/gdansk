from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def test_module_entrypoint_version():
    completed = subprocess.run(
        [sys.executable, "-m", "gdansk", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "gdansk" in completed.stdout
