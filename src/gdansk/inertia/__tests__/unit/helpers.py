from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final, TypedDict

from fastapi import FastAPI
from pydantic import BaseModel, Field
from starlette.requests import Request

from gdansk.__tests__.unit.conftest import SessionStateMiddleware
from gdansk.inertia import Always, Defer, Merge, Once, OptionalProp, Scroll  # noqa: TC001

if TYPE_CHECKING:
    from gdansk import Ship


class EmptyPageProps(BaseModel):
    pass


class HomeProps(BaseModel):
    message: str


class LazyMessagePageProps(BaseModel):
    message: object


class MessagePageProps(BaseModel):
    message: str


class Announcement(TypedDict):
    id: int
    title: str


class ConversationMessage(TypedDict):
    body: str
    id: int


class Conversation(TypedDict):
    messages: list[ConversationMessage]


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


class PartialReloadPageProps(BaseModel):
    always_value: Always[str]
    deferred_value: Defer[str]
    optional_value: OptionalProp[str]
    plain_value: object


class OncePageProps(BaseModel):
    expensive: Once[str]


class OnceOptionsPageProps(BaseModel):
    aliased: Once[str]
    expired: Once[str]
    fresh_value: Once[str]
    stale: Once[str]


class NestedAuthPageProps(BaseModel):
    auth: object


class MergeMetadataPageProps(BaseModel):
    announcements: Merge[list[Announcement]]
    conversation: Merge[Conversation]
    users: Merge[list[User]]


class ScrollPageProps(BaseModel):
    feed: Scroll[Feed]


class SharedPageProps(BaseModel):
    headline: str | None = Field(default=None, min_length=2)
    session_token: object | None = Field(default=None, serialization_alias="sessionToken")
    summary: str | None = None


_V3_REQUIRED_PAGE_KEYS: Final[frozenset[str]] = frozenset({"component", "flash", "props", "url", "version"})
_V3_CLIENT_OWNED_PAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "initialDeferredProps",
        "optimisticUpdatedAt",
        "rememberedState",
    },
)
_UNSUPPORTED_3X_PAGE_KEYS: Final[frozenset[str]] = frozenset({"rescuedProps"})


def _page_app(ship: Ship) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with ship.lifespan(watch=None):
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionStateMiddleware)
    return app


def _request(*, path: str) -> Request:
    return Request(
        {
            "client": ("127.0.0.1", 123),
            "headers": [],
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "type": "http",
        },
    )


def _assert_released_v3_page_payload(page: dict[str, Any]) -> None:
    assert page.keys() >= _V3_REQUIRED_PAGE_KEYS
    assert _V3_CLIENT_OWNED_PAGE_KEYS.isdisjoint(page)
    assert _UNSUPPORTED_3X_PAGE_KEYS.isdisjoint(page)

    props = page["props"]
    assert isinstance(props, dict)
    assert "errors" in props
    assert "deferred" not in props

    for optional_boolean_key in ("clearHistory", "encryptHistory", "preserveFragment"):
        assert page.get(optional_boolean_key) is not False
