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

from gdansk import Metadata, Ship, Vite, always, defer
from gdansk.fastapi import inertia_request_validation_exception_handler

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.responses import Response

    from gdansk.inertia import InertiaPage, InertiaResponse

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


ship = Ship(vite=Vite(Path(__file__).parent / "src/gdansk_inertia_example/views"))
inertia = ship.inertia()
page_dependency = inertia.dependency()
PageDependency = Annotated["InertiaPage", Depends(page_dependency)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with inertia.lifespan(watch=not PRODUCTION):
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
    return await page.render(
        "/",
        {
            "activity": defer(build_activity, group="activity"),
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


@app.get("/inertia")
async def inertia_docs(page: PageDependency) -> Response:
    return page.location("https://inertiajs.com/")
