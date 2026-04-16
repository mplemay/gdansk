from __future__ import annotations

import httpx
import pytest

from gdansk.vite import Vite


def test_vite_rejects_invalid_runtime_port():
    with pytest.raises(ValueError, match="runtime port"):
        Vite(port=0)


async def test_vite_watch_session_requires_bind_for_dev(tmp_path):
    (tmp_path / "widgets").mkdir()
    vite = Vite()
    with pytest.raises(RuntimeError, match="not bound"):
        async with vite(watch=True):
            pytest.fail("unbound Vite should not enter dev mode")


async def test_vite_watch_session_noop_for_watch_none(tmp_path):
    (tmp_path / "widgets").mkdir()
    vite = Vite()
    async with httpx.AsyncClient() as client:
        vite.bind_runtime(cwd=tmp_path, client=client)
        async with vite(watch=None):
            assert not vite.has_runtime()
