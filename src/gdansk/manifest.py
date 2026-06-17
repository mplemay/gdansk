from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InlineWidgetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    script: str
    styles: list[str]


class WidgetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry: str
    inline: InlineWidgetManifest


class GdanskManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    out_dir: str = Field(alias="outDir")
    root: str
    widgets: dict[str, WidgetManifest]
