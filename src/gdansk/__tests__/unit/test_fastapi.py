from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Body, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from gdansk import Metadata, Ship, Vite, defer
from gdansk.__tests__.unit.conftest import SessionStateMiddleware, write_page_manifest
from gdansk.fastapi import inertia_request_validation_exception_handler
from gdansk.inertia import InertiaPage  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


class FeedbackPayload(BaseModel):
    name: str = Field(min_length=2)
    topic: str = Field(min_length=3)


def test_fastapi_inertia_validation_and_flash_flow(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), metadata=Metadata(title="Gdansk"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with ship.lifespan(watch=None):
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionStateMiddleware)
    app.add_exception_handler(RequestValidationError, inertia_request_validation_exception_handler)
    app.mount(ship.assets_path, ship.assets)

    @app.get("/")
    async def home(page: InertiaPage = Depends(ship.page)):
        return await page.render(
            "/",
            {
                "activity": defer(lambda: ["Ship lifecycle", "Session-backed flash"], group="activity"),
                "headline": "FastAPI + Inertia",
            },
            metadata=Metadata(description="FastAPI Inertia example"),
        )

    @app.post("/feedback")
    async def feedback(
        page: InertiaPage = Depends(ship.page),
        payload: FeedbackPayload = Body(),
    ):
        page.flash(message=f"Thanks, {payload.name}.")
        return page.back()

    with TestClient(app) as client:
        invalid = client.post(
            "/feedback",
            headers={
                "Referer": "http://testserver/",
                "X-Inertia": "true",
            },
            json={"name": "", "topic": "ok"},
            follow_redirects=False,
        )
        after_invalid = client.get("/", headers={"X-Inertia": "true"}, follow_redirects=False)
        valid = client.post(
            "/feedback",
            headers={
                "Referer": "http://testserver/",
                "X-Inertia": "true",
            },
            json={"name": "Marta", "topic": "Design system"},
            follow_redirects=False,
        )
        after_valid = client.get("/", headers={"X-Inertia": "true"}, follow_redirects=False)
        partial = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "activity",
            },
            follow_redirects=False,
        )

    assert invalid.status_code == 303
    assert invalid.headers["location"] == "http://testserver/"
    assert after_invalid.json()["props"]["errors"] == {
        "name": "String should have at least 2 characters",
        "topic": "String should have at least 3 characters",
    }
    assert after_invalid.json()["flash"] == {}

    assert valid.status_code == 303
    assert after_valid.json()["props"]["errors"] == {}
    assert after_valid.json()["flash"] == {"message": "Thanks, Marta."}

    assert partial.json()["props"] == {
        "activity": ["Ship lifecycle", "Session-backed flash"],
        "errors": {},
    }


def test_fastapi_inertia_preserves_fragment_and_reuses_once_shared_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with ship.lifespan(watch=None):
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionStateMiddleware)
    app.mount(ship.assets_path, ship.assets)

    @app.get("/")
    async def home(page: InertiaPage = Depends(ship.page)):
        page.share_once(session_token=lambda: "token-1")
        return await page.render("/", {"headline": "Dashboard"})

    @app.post("/save")
    async def save(page: InertiaPage = Depends(ship.page)):
        return page.redirect("/", preserve_fragment=True)

    with TestClient(app) as client:
        initial = client.get("/", headers={"X-Inertia": "true"}, follow_redirects=False)
        redirect = client.post("/save", headers={"X-Inertia": "true"}, follow_redirects=False)
        after_redirect = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Except-Once-Props": "session_token",
            },
            follow_redirects=False,
        )

    assert initial.json()["onceProps"] == {
        "session_token": {
            "expiresAt": None,
            "prop": "session_token",
        },
    }
    assert initial.json()["sharedProps"] == ["session_token"]
    first_token = initial.json()["props"]["session_token"]
    assert isinstance(first_token, str)
    assert first_token.startswith("token-")
    assert first_token.removeprefix("token-") == "1"

    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/"

    assert after_redirect.json()["preserveFragment"] is True
    assert after_redirect.json()["sharedProps"] == ["session_token"]
    assert "session_token" not in after_redirect.json()["props"]
    assert after_redirect.json()["onceProps"] == initial.json()["onceProps"]
