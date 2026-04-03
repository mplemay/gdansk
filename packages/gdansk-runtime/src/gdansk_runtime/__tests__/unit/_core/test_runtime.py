from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gdansk_runtime import Runtime

if TYPE_CHECKING:
    from pathlib import Path

    _typing_runtime = Runtime(package_json="package.json")


def test_runtime_accepts_package_json_paths(tmp_path: Path):
    package_json = tmp_path / "package.json"

    assert isinstance(Runtime(package_json=package_json), Runtime)
    assert isinstance(Runtime(package_json=str(package_json)), Runtime)


def test_runtime_lock_requires_package_json():
    with pytest.raises(RuntimeError, match="package_json"):
        Runtime().lock()


def test_runtime_sync_requires_package_json():
    with pytest.raises(RuntimeError, match="package_json"):
        Runtime().sync()


@pytest.mark.anyio
async def test_runtime_alock_requires_package_json():
    with pytest.raises(RuntimeError, match="package_json"):
        await Runtime().alock()
