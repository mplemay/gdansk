from __future__ import annotations

from typing import Any, TypedDict, cast

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from gdansk import Ship, Vite
from gdansk.inertia import Always, Defer, Inertia, InertiaPage, Merge, Once, OptionalProp, Scroll


class Metric(TypedDict):
    label: str
    value: int


class FeedItem(TypedDict):
    id: int
    title: str


class Feed(TypedDict):
    items: list[FeedItem]


class SharedProps(BaseModel):
    headline: str | None = None
    session_token: Once[str] | None = Field(default=None, serialization_alias="sessionToken")


class HomeProps(BaseModel):
    activity: Defer[list[str]]
    feed: Scroll[Feed]
    metrics: Always[list[Metric]]
    optional_value: OptionalProp[str]
    updated_at: Merge[str] = Field(serialization_alias="updatedAt")


class AlternateHomeProps(BaseModel):
    message: str


class PageSharedProps(BaseModel):
    page_summary: str | None = Field(default=None, serialization_alias="pageSummary")


class DuplicateSharedProps(BaseModel):
    metrics: str | None = None


def test_inertia_generates_page_props_from_unwrapped_prop_payloads(page_views_path):
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=SharedProps))
    app = FastAPI()

    @app.get("/")
    @ship.page()
    async def home(page: InertiaPage[SharedProps] = Depends(ship.page)) -> HomeProps:
        raise AssertionError(page)

    ship.generate_page_types(app=app)

    generated = (page_views_path / ".gdansk" / "pages.ts").read_text(encoding="utf-8")

    assert 'import { z } from "@gdansk/vite/zod";' in generated
    assert '"/": z.fromJSONSchema(rawPageSchemas["/"] as Parameters<typeof z.fromJSONSchema>[0]),' in generated
    assert "activity?: Array<string>;" in generated
    assert "feed: {" in generated
    assert "metrics: Array<{" in generated
    assert "optional_value?: string;" in generated
    assert "updatedAt: string;" in generated
    assert "headline?: string | null;" in generated
    assert "sessionToken?: string | null;" in generated
    assert "errors: Record<string, string | Record<string, string>>;" in generated
    assert "PropSource" not in generated
    assert "always_include" not in generated


def test_inertia_page_type_generation_resolves_implicit_route_components(page_views_path):
    ship = Ship(vite=Vite(page_views_path))
    app = FastAPI()

    @app.get("/dashboard/{report_id}")
    @ship.page()
    async def report(report_id: str) -> AlternateHomeProps:
        raise AssertionError(report_id)

    ship.generate_page_types(app=app)

    generated = (page_views_path / ".gdansk" / "pages.ts").read_text(encoding="utf-8")

    assert '"dashboard/{report_id}"' in generated
    assert "message: string;" in generated


def test_inertia_page_type_generation_accepts_props_and_shared_overrides(page_views_path):
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=SharedProps))
    app = FastAPI()

    @app.get("/summary")
    @ship.page("summary", props=AlternateHomeProps, shared=PageSharedProps)
    async def summary() -> dict[str, object]:
        return {"message": "ok"}

    ship.generate_page_types(app=app)

    generated = (page_views_path / ".gdansk" / "pages.ts").read_text(encoding="utf-8")

    assert '"summary"' in generated
    assert "message: string;" in generated
    assert "pageSummary?: string | null;" in generated
    assert "headline?: string | null;" not in generated


def test_inertia_page_type_generation_unions_multiple_models_for_same_component(page_views_path):
    ship = Ship(vite=Vite(page_views_path))
    app = FastAPI()

    @app.get("/first")
    @ship.page("shared")
    async def first() -> HomeProps:
        raise AssertionError

    @app.get("/second")
    @ship.page("shared")
    async def second() -> AlternateHomeProps:
        raise AssertionError

    ship.generate_page_types(app=app)

    generated = (page_views_path / ".gdansk" / "pages.ts").read_text(encoding="utf-8")

    assert '"shared": {' in generated
    assert '"anyOf": [' in generated
    assert "updatedAt: string;" in generated
    assert "message: string;" in generated


def test_inertia_page_type_generation_rejects_duplicate_route_and_shared_keys(page_views_path):
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=DuplicateSharedProps))
    app = FastAPI()

    @app.get("/")
    @ship.page()
    async def home() -> HomeProps:
        raise AssertionError

    with pytest.raises(RuntimeError, match='prop "metrics"'):
        ship.generate_page_types(app=app)


def test_inertia_page_type_generation_rejects_invalid_override_models(page_views_path):
    ship = Ship(vite=Vite(page_views_path))

    with pytest.raises(TypeError, match="route props model"):
        ship.page(props=cast("Any", dict))


def test_inertia_page_type_generation_requires_override_for_multi_model_unions(page_views_path):
    ship = Ship(vite=Vite(page_views_path))

    with pytest.raises(TypeError, match="multiple pydantic return models"):

        @ship.page()
        async def home() -> HomeProps | AlternateHomeProps:
            raise AssertionError
