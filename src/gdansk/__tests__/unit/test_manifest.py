from __future__ import annotations

import pytest
from pydantic import ValidationError

from gdansk.manifest import GdanskManifest


def test_gdansk_manifest_accepts_outdir_alias() -> None:
    manifest = GdanskManifest.model_validate(
        {
            "outDir": "dist",
            "root": "/workspace/views",
            "widgets": {
                "hello": {
                    "entry": "hello/widget.tsx",
                    "inline": {
                        "script": 'console.log("hello");',
                        "styles": [".hello { color: red; }"],
                    },
                },
            },
        },
    )
    assert manifest.out_dir == "dist"
    assert manifest.widgets["hello"].inline.script == 'console.log("hello");'


def test_gdansk_manifest_rejects_external_asset_widget_shape() -> None:
    with pytest.raises(ValidationError):
        GdanskManifest.model_validate(
            {
                "outDir": "dist",
                "root": "/workspace/views",
                "widgets": {
                    "hello": {
                        "client": "dist/hello/client.js",
                        "css": ["dist/hello/client.css"],
                        "entry": "hello/widget.tsx",
                    },
                },
            },
        )
