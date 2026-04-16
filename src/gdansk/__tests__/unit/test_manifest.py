from __future__ import annotations

from gdansk.manifest import GdanskManifest


def test_gdansk_manifest_accepts_outdir_alias() -> None:
    manifest = GdanskManifest.model_validate(
        {
            "outDir": "dist",
            "root": "/workspace/views",
            "widgets": {},
        },
    )
    assert manifest.out_dir == "dist"
