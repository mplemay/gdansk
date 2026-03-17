from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

VIEWS_ROOT = Path(os.environ["GDANSK_TAILWIND_VIEWS_ROOT"])
TOKEN_RE = re.compile(r"[A-Za-z0-9_:/-]+")


def _collect_tokens() -> tuple[list[str], list[str]]:
    watch_files: list[str] = []
    watch_directories: set[str] = set()
    tokens: set[str] = set()

    for candidate in VIEWS_ROOT.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix not in {".tsx", ".jsx", ".js", ".html"}:
            continue
        watch_files.append(str(candidate))
        if candidate.parent != VIEWS_ROOT:
            watch_directories.add(str(candidate.parent))
        content = candidate.read_text(encoding="utf-8")
        for token in TOKEN_RE.findall(content):
            if "-" in token:
                tokens.add(token)

    config_path = VIEWS_ROOT / "tailwind.config.js"
    if config_path.is_file():
        watch_files.append(str(config_path))
        watch_directories.add(str(config_path.parent))
        config_token = config_path.read_text(encoding="utf-8").strip().replace('"', "")
        if config_token:
            tokens.add(f"config-{config_token}")

    return sorted(tokens), sorted(set(watch_files) | watch_directories)


def _generate(payload: dict[str, object]) -> dict[str, object]:
    css_path = Path(str(payload["id"]))
    content = str(payload["content"])
    if "tailwindcss" not in content:
        return {
            "kind": "generated",
            "id": str(css_path),
            "is_tailwind_root": False,
            "watch_files": [],
            "watch_directories": [],
        }

    tokens, watch_entries = _collect_tokens()
    watch_files = [entry for entry in watch_entries if Path(entry).is_file()]
    watch_directories = [entry for entry in watch_entries if Path(entry).is_dir()]

    cleaned = content.replace('@import "tailwindcss";', "").replace("@import 'tailwindcss';", "").strip()
    code_parts = [cleaned] if cleaned else []
    for token in tokens:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", token)
        code_parts.append(f":root{{--tw-{safe}:1;}}")

    return {
        "kind": "generated",
        "id": str(css_path),
        "is_tailwind_root": True,
        "code": "\n".join(code_parts) + "\n",
        "watch_files": watch_files,
        "watch_directories": watch_directories,
    }


for line in sys.stdin:
    if not line.strip():
        continue
    payload = json.loads(line)
    if payload.get("kind") != "generate":
        response = {"kind": "error", "error": f"unsupported request kind {payload.get('kind')}"}
    else:
        response = _generate(payload)
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
