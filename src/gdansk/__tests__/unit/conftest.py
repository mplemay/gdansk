from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


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


class SessionStateMiddleware:
    def __init__(self, app) -> None:
        self.app = app
        self._session: dict[str, Any] = {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            scope["session"] = self._session

        await self.app(scope, receive, send)


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


@pytest.fixture
def page_views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "src" / "Pages").mkdir(parents=True)
    (views / "src" / "Pages" / "Home.tsx").write_text("export default function Home() { return null; }\n")
    (views / "src" / "main.tsx").write_text("export {};\n")
    (views / "dist").mkdir(parents=True, exist_ok=True)
    return views


def write_page_manifest(
    views: Path,
    *,
    assets_dir: str = "dist",
    css: list[str] | None = None,
    entry: str = "src/main.tsx",
    file: str = "assets/main.js",
    imports: dict[str, Any] | None = None,
) -> None:
    manifest: dict[str, Any] = {
        entry: {
            "css": css or ["assets/main.css"],
            "file": file,
            "imports": list((imports or {}).keys()),
            "isEntry": True,
            "src": entry,
        },
        **(imports or {}),
    }

    path = views / assets_dir / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
