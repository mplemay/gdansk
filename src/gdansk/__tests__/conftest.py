from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text(
        "export default function App() { return null; }\n",
        encoding="utf-8",
    )
    (views / "dist").mkdir(parents=True, exist_ok=True)
    return views
