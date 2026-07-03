from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WidgetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry: str
    html: str


class GdanskManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    out_dir: str = Field(alias="outDir")
    root: str
    widgets: dict[str, WidgetManifest]


class DevelopmentWidgetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry: str
    origin: str
    page: str


class GdanskDevelopmentManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: str
    widgets: dict[str, DevelopmentWidgetManifest]
