from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_MAX_TOKEN_LEN = 128

_CONTENT_EXTENSIONS = frozenset(
    {
        ".css",
        ".html",
        ".js",
        ".jsx",
        ".md",
        ".mdx",
        ".ts",
        ".tsx",
    },
)
_IGNORED_DIRECTORIES = frozenset({".gdansk", ".git", "build", "dist", "node_modules"})
_CANDIDATE_PATTERN = re.compile(r"[A-Za-z0-9-_:./[\]%]+")


def _should_scan_file(path: Path) -> bool:
    return path.suffix.lower() in _CONTENT_EXTENSIONS


def _is_likely_candidate(token: str) -> bool:
    if len(token) == 0 or len(token) > _MAX_TOKEN_LEN:
        return False
    if token.startswith((".", "/", "@")) or "://" in token or token.endswith((".tsx", ".ts", ".jsx", ".js")):
        return False
    return bool(re.search(r"[-:[\]/]", token)) or token in {"flex", "grid"}


def collect_candidates(root: Path) -> list[str]:
    candidates: set[str] = set()
    root = root.resolve()

    for dirpath, dirnames, filenames in root.walk(top_down=True):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRECTORIES]
        for name in filenames:
            path = dirpath / name
            if not path.is_file() or not _should_scan_file(path):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in _CANDIDATE_PATTERN.finditer(source):
                token = match.group(0)
                if _is_likely_candidate(token):
                    candidates.add(token)

    return sorted(candidates)
