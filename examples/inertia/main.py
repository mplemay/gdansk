from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from os import getenv
from pathlib import Path
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from gdansk import Metadata, Ship, Vite, always, deep_merge, defer, merge, scroll
from gdansk.fastapi import inertia_request_validation_exception_handler
from gdansk.inertia import InertiaPage  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.responses import Response

    from gdansk.inertia import InertiaResponse

PRODUCTION = getenv("PRODUCTION") == "true"
SESSION_SECRET = getenv("SESSION_SECRET") or token_urlsafe(32)


class FeedbackPayload(BaseModel):
    name: str = Field(min_length=2)
    topic: str = Field(min_length=3)


def build_metrics() -> list[dict[str, str]]:
    return [
        {
            "label": "Protocol",
            "note": "HTML first, JSON after hydrate",
            "value": "Inertia",
        },
        {
            "label": "Transport",
            "note": "One FastAPI route handles both modes",
            "value": "Ship",
        },
        {
            "label": "Frontend",
            "note": "Convention-driven app/page.tsx + layout.tsx",
            "value": "gdanskPages",
        },
    ]


def build_activity() -> list[str]:
    timestamp = datetime.now(UTC).strftime("%H:%M UTC")
    return [
        f"{timestamp}: Deferred activity refreshed through a partial reload.",
        "Validation errors round-trip through the session and land in props.errors.",
        "Flash data survives redirects without adding another rendering layer.",
    ]


def build_announcements() -> list[dict[str, str]]:
    timestamp = datetime.now(UTC).strftime("%H:%M:%S")
    key = datetime.now(UTC).strftime("%H%M%S%f")
    return [
        {
            "id": f"announcement-{key}",
            "label": f"Announcement {timestamp}",
            "note": "This item is appended through merge() during partial reloads.",
        },
    ]


def build_conversation() -> dict[str, object]:
    timestamp = datetime.now(UTC).strftime("%H:%M:%S")
    key = datetime.now(UTC).strftime("%H%M%S%f")
    return {
        "messages": [
            {
                "author": "Ship",
                "body": f"Deep-merged message at {timestamp}",
                "id": f"message-{key}",
            },
        ],
        "summary": {
            "updatedAt": timestamp,
        },
    }


def build_feed() -> dict[str, object]:
    timestamp = datetime.now(UTC).strftime("%H:%M:%S")
    key = datetime.now(UTC).strftime("%H%M%S%f")
    return {
        "items": [
            {
                "id": f"feed-{key}",
                "text": f"Scroll payload captured at {timestamp}",
            },
        ],
        "pagination": {
            "current": 2,
            "next": 3,
            "previous": 1,
        },
    }


ship = Ship(vite=Vite(Path(__file__).parent / "src/gdansk_inertia_example/views"))
ship.inertia(encrypt_history=True)
type PageDependency = Annotated["InertiaPage", Depends(ship.page)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with ship.lifespan(watch=not PRODUCTION):
        yield


app = FastAPI(title="Gdansk Inertia Example", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.add_exception_handler(RequestValidationError, inertia_request_validation_exception_handler)
app.mount(ship.assets_path, ship.assets)


@app.get("/")
async def home(page: PageDependency) -> InertiaResponse:
    page.share(
        headline="Ship-backed Inertia pages",
        summary="A FastAPI route can render the initial shell, switch to JSON visits, and keep using the frontend "
        "tooling gdansk already owns.",
    )
    page.share_once(sessionToken=lambda: token_urlsafe(6))
    return await page.render(
        "/",
        {
            "activity": defer(build_activity, group="activity"),
            "announcements": merge(build_announcements()).append(match_on="id"),
            "conversation": deep_merge(build_conversation(), match_on="messages.id"),
            "feed": scroll(
                build_feed(),
                current_page_path="pagination.current",
                items_path="items",
                next_page_path="pagination.next",
                page_name="feed_page",
                previous_page_path="pagination.previous",
            ),
            "metrics": always(build_metrics),
            "updatedAt": always(datetime.now(UTC).strftime("%B %d, %Y")),
        },
        metadata=Metadata(
            description="Ship-backed Inertia pages for FastAPI",
            title="Gdansk Inertia",
        ),
    )


@app.post("/feedback")
async def feedback(payload: FeedbackPayload, page: PageDependency) -> Response:
    page.flash(message=f"Thanks, {payload.name}. We'll follow up about {payload.topic}.")
    return page.back()


@app.post("/jump-to-activity")
async def jump_to_activity(page: PageDependency) -> Response:
    return page.location("/#activity")


@app.get("/inertia")
async def inertia_docs(page: PageDependency) -> Response:
    return page.location("https://inertiajs.com/")
