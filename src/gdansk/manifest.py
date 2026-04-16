from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GdanskManifestWidget(BaseModel):
    model_config = ConfigDict(frozen=True)

    client: str
    css: list[str]
    entry: str


class GdanskManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    out_dir: str = Field(alias="outDir")
    root: str
    widgets: dict[str, GdanskManifestWidget]
