from __future__ import annotations

from fastapi import FastAPI
from starlette.requests import Request  # noqa: TC002
from starlette.testclient import TestClient

from gdansk import Always, Merge, Ship, Vite
from gdansk.__tests__.unit.conftest import write_page_manifest


def _build_app(tmp_path) -> FastAPI:
    views = tmp_path / "views"
    write_page_manifest(views)
    ship = Ship(vite=Vite(views))
    app = FastAPI()

    @app.get("/")
    async def home(request: Request):
        page = ship.page(request)
        return await page.render(
            "/",
            {
                "conversation": Merge(
                    value={
                        "messages": [
                            {
                                "author": "Ship",
                                "body": "Deep-merged message at 04:11:33",
                                "id": "message-1",
                            },
                        ],
                        "summary": {
                            "updatedAt": "04:11:33",
                        },
                    },
                    deep=True,
                    match_on="messages.id",
                ),
                "metrics": Always(
                    value=[
                        {
                            "label": "Protocol",
                            "note": "HTML first, JSON after hydrate",
                            "value": "Inertia",
                        },
                    ],
                ),
                "updatedAt": Always(value="April 23, 2026"),
            },
        )

    @app.post("/jump-to-activity")
    async def jump_to_activity(request: Request):
        page = ship.page(request)
        return page.location("/#activity")

    return app


def test_inertia_page_includes_conversation_and_handles_partial_reload(tmp_path):
    with TestClient(_build_app(tmp_path)) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        partial = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "metrics",
            },
        )
        jump = client.post("/jump-to-activity", headers={"X-Inertia": "true"}, follow_redirects=False)

    assert initial.status_code == 200

    initial_props = initial.json()["props"]
    assert "conversation" in initial_props
    assert initial_props["conversation"]["messages"]

    assert partial.status_code == 200

    partial_props = partial.json()["props"]
    assert "conversation" not in partial_props
    assert partial_props["errors"] == {}
    assert partial_props["metrics"]
    assert partial_props["updatedAt"]

    assert jump.status_code == 409
    assert jump.headers["X-Inertia-Location"] == "/#activity"
