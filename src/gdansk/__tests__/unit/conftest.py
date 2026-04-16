from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class FakeResponse:
    def __init__(self, *, status_code: int = 200) -> None:
        self.status_code = status_code


class FakeClient:
    def __init__(self) -> None:
        self.get_calls: list[tuple[str, float | None]] = []
        self.status_code = 200

    async def get(self, url: str, **kwargs: float | None) -> FakeResponse:
        timeout = kwargs.get("timeout")
        self.get_calls.append((url, timeout))
        return FakeResponse(status_code=self.status_code)


class FakeProcess:
    returncode: int | None = None


class FakeManagedProcess:
    def __init__(self) -> None:
        self.killed = False
        self.returncode: int | None = None
        self.terminated = False
        self.waited = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")
    (views / "dist").mkdir(parents=True, exist_ok=True)
    return views


def write_manifest(views: Path, *, assets_dir: str = "dist", manifest_out_dir: str | None = None) -> None:
    out_dir = manifest_out_dir or assets_dir
    manifest: dict[str, Any] = {
        "outDir": out_dir,
        "root": str(views),
        "widgets": {
            "hello": {
                "client": f"{out_dir}/hello/client.js",
                "css": [f"{out_dir}/hello/client.css"],
                "entry": "hello/widget.tsx",
            },
        },
    }

    path = views / assets_dir / "gdansk-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
