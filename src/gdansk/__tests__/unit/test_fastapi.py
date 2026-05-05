from __future__ import annotations

from contextlib import asynccontextmanager
from inspect import Signature, signature
from typing import TYPE_CHECKING, TypedDict

from fastapi import Body, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from gdansk import Always, Defer, Merge, Metadata, Once, OptionalProp, Scroll, Ship, Vite
from gdansk.__tests__.unit.conftest import SessionStateMiddleware, write_page_manifest
from gdansk.fastapi import inertia_request_validation_exception_handler
from gdansk.inertia import InertiaPage

if TYPE_CHECKING:
    from pathlib import Path


class FeedbackPayload(BaseModel):
    name: str = Field(min_length=2)
    topic: str = Field(min_length=3)


class Announcement(TypedDict):
    id: int
    title: str


class ConversationMessage(TypedDict):
    body: str
    id: int


class ConversationSummary(TypedDict):
    updatedAt: str


class Conversation(TypedDict):
    messages: list[ConversationMessage]
    summary: ConversationSummary


class FeedItem(TypedDict):
    id: int
    title: str


class FeedPagination(TypedDict):
    current: int
    next: int
    previous: int


class Feed(TypedDict):
    items: list[FeedItem]
    pagination: FeedPagination


class User(TypedDict):
    id: int
    name: str


class ValidationPageProps(BaseModel):
    activity: Defer[list[str]]
    headline: str


class HeadlinePageProps(BaseModel):
    headline: str


class DecoratedPageProps(BaseModel):
    activity: Defer[list[str]]
    always_value: Always[str]
    announcements: Merge[list[Announcement]]
    conversation: Merge[Conversation]
    feed: Scroll[Feed]
    optional_value: OptionalProp[str]
    profile: Once[str]
    updated_at: str = Field(serialization_alias="updatedAt")
    users: Merge[list[User]]


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
    @ship.page("/", metadata=Metadata(description="FastAPI Inertia example"))
    async def home(page: InertiaPage = Depends(ship.page)) -> ValidationPageProps:
        page.share(source="decorated")
        return ValidationPageProps(
            activity=Defer(value=lambda: ["Ship lifecycle", "Session-backed flash"], group="activity"),
            headline="FastAPI + Inertia",
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
    assert after_valid.json()["props"]["source"] == "decorated"
    assert after_valid.json()["sharedProps"] == ["source"]

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
    @ship.page("/")
    async def home(page: InertiaPage = Depends(ship.page)) -> HeadlinePageProps:
        page.share_once(session_token=lambda: "token-1")
        return HeadlinePageProps(headline="Dashboard")

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


def test_ship_page_signature_preserves_fastapi_dependency_shape(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))

    ship_page_signature = signature(ship.page)
    params = list(ship_page_signature.parameters.values())

    assert len(params) == 1
    assert params[0].name == "request"
    assert params[0].annotation is not Signature.empty
    assert ship_page_signature.return_annotation is InertiaPage


def test_fastapi_inertia_page_decorator_renders_model_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), metadata=Metadata(title="Gdansk"))
    activity_calls: list[str] = []

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with ship.lifespan(watch=None):
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionStateMiddleware)
    app.mount(ship.assets_path, ship.assets)

    def load_activity() -> list[str]:
        activity_calls.append("activity")
        return ["deferred activity"]

    @app.get("/")
    @ship.page("/", metadata=Metadata(description="Decorated page"))
    async def home() -> DecoratedPageProps:
        return DecoratedPageProps(
            activity=Defer(value=load_activity, group="activity"),
            always_value=Always(value="always"),
            announcements=Merge(
                value=[{"id": 2, "title": "Announcement"}],
                match_on="id",
                mode="prepend",
            ),
            conversation=Merge(
                value={
                    "messages": [{"body": "Hello", "id": 3}],
                    "summary": {"updatedAt": "10:00"},
                },
                deep=True,
                match_on="messages.id",
            ),
            feed=Scroll(
                value={
                    "items": [{"id": 4, "title": "Feed item"}],
                    "pagination": {
                        "current": 2,
                        "next": 3,
                        "previous": 1,
                    },
                },
                current_page_path="pagination.current",
                items_path="items",
                next_page_path="pagination.next",
                page_name="feed_page",
                previous_page_path="pagination.previous",
            ),
            optional_value=OptionalProp(value="optional"),
            profile=Once(value="Ada", key="profile-cache"),
            updated_at="May 5, 2026",
            users=Merge(value=[{"id": 1, "name": "Ada"}], match_on="id"),
        )

    with TestClient(app) as client:
        html = client.get("/", follow_redirects=False)
        initial = client.get("/", headers={"X-Inertia": "true"}, follow_redirects=False)

    assert activity_calls == []

    with TestClient(app) as client:
        partial = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "activity",
            },
            follow_redirects=False,
        )

    assert html.status_code == 200
    assert "<title>Gdansk</title>" in html.text
    assert '<meta name="description" content="Decorated page" />' in html.text

    initial_page = initial.json()
    assert initial_page["component"] == "/"
    assert initial_page["props"] == {
        "always_value": "always",
        "announcements": [{"id": 2, "title": "Announcement"}],
        "conversation": {
            "messages": [{"body": "Hello", "id": 3}],
            "summary": {"updatedAt": "10:00"},
        },
        "errors": {},
        "feed": {
            "items": [{"id": 4, "title": "Feed item"}],
            "pagination": {
                "current": 2,
                "next": 3,
                "previous": 1,
            },
        },
        "profile": "Ada",
        "updatedAt": "May 5, 2026",
        "users": [{"id": 1, "name": "Ada"}],
    }
    assert initial_page["deferredProps"] == {"activity": ["activity"]}
    assert initial_page["mergeProps"] == ["feed.items", "users"]
    assert initial_page["prependProps"] == ["announcements"]
    assert initial_page["deepMergeProps"] == ["conversation"]
    assert initial_page["matchPropsOn"] == [
        "announcements.id",
        "conversation.messages.id",
        "users.id",
    ]
    assert initial_page["onceProps"] == {
        "profile-cache": {
            "expiresAt": None,
            "prop": "profile",
        },
    }
    assert initial_page["scrollProps"] == {
        "feed": {
            "currentPage": 2,
            "nextPage": 3,
            "pageName": "feed_page",
            "previousPage": 1,
            "reset": False,
        },
    }
    assert partial.json()["props"] == {
        "activity": ["deferred activity"],
        "always_value": "always",
        "errors": {},
    }
    assert activity_calls == ["activity"]
