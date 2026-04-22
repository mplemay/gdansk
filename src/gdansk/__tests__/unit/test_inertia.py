from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from gdansk import Metadata, Ship, Vite, always, defer, optional
from gdansk.__tests__.unit.conftest import SessionStateMiddleware, write_page_manifest

if TYPE_CHECKING:
    from starlette.requests import Request


def test_inertia_renders_production_html_shell(page_views_path: Path):
    write_page_manifest(
        page_views_path,
        imports={
            "assets/vendor.js": {
                "css": ["assets/vendor.css"],
                "file": "assets/vendor.js",
            },
        },
    )
    ship = Ship(vite=Vite(page_views_path), metadata=Metadata(title="Base title"))
    inertia = ship.inertia()
    page = {
        "component": "Home",
        "flash": {},
        "props": {
            "errors": {},
            "message": "hello",
        },
        "url": "/",
        "version": inertia.version(),
    }

    html = inertia.render_html(metadata=Metadata(description="Page description"), page=page)

    assert "<title>Base title</title>" in html
    assert '<meta name="description" content="Page description" />' in html
    assert '<script data-page="app" type="application/json">' in html
    assert '<div id="app"></div>' in html
    assert '<link rel="stylesheet" href="/dist/assets/vendor.css">' in html
    assert '<link rel="stylesheet" href="/dist/assets/main.css">' in html
    assert '<script type="module" src="/dist/assets/main.js"></script>' in html


def test_inertia_renders_dev_html_shell(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))
    ship._dev = True
    ship._vite._origin = "http://127.0.0.1:5173"
    inertia = ship.inertia()
    page = {
        "component": "Home",
        "flash": {},
        "props": {
            "errors": {},
        },
        "url": "/",
        "version": None,
    }

    html = inertia.render_html(metadata=None, page=page)

    assert 'import RefreshRuntime from "http://127.0.0.1:5173/@react-refresh"' in html
    assert '<script type="module" src="http://127.0.0.1:5173/@vite/client"></script>' in html
    assert '<script type="module" src="http://127.0.0.1:5173/src/main.tsx"></script>' in html
    assert '<link rel="stylesheet"' not in html


def test_inertia_json_response_has_expected_page_shape(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    inertia = ship.inertia()

    async def home(request: Request):
        page = inertia.dependency()(request)
        page.share(shared=lambda: "shared")
        return await page.render("Home", {"message": lambda: "hello"})

    with TestClient(_page_app(inertia, routes=[Route("/", home)])) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.status_code == 200
    assert response.headers["X-Inertia"] == "true"
    assert response.headers["Vary"] == "X-Inertia"
    assert response.json() == {
        "component": "Home",
        "flash": {},
        "props": {
            "errors": {},
            "message": "hello",
            "shared": "shared",
        },
        "url": "/",
        "version": inertia.version(),
    }


def test_inertia_returns_409_for_stale_asset_versions(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    inertia = ship.inertia()

    async def home(request: Request):
        page = inertia.dependency()(request)
        return await page.render("Home", {})

    with TestClient(_page_app(inertia, routes=[Route("/", home)])) as client:
        response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Version": "stale-build",
            },
        )

    assert response.status_code == 409
    assert response.headers["Vary"] == "X-Inertia"
    assert response.headers["X-Inertia-Location"] == "http://testserver/"


def test_inertia_partial_reload_respects_optional_always_and_deferred_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    inertia = ship.inertia()

    async def home(request: Request):
        page = inertia.dependency()(request)
        return await page.render(
            "Home",
            {
                "always_value": always(lambda: "always"),
                "deferred_value": defer(lambda: "deferred", group="activity"),
                "optional_value": optional(lambda: "optional"),
                "plain_value": lambda: "plain",
            },
        )

    with TestClient(_page_app(inertia, routes=[Route("/", home)])) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        partial_only = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "Home",
                "X-Inertia-Partial-Data": "deferred_value",
            },
        )
        partial_except = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "Home",
                "X-Inertia-Partial-Except": "plain_value",
            },
        )

    assert initial.json()["props"] == {
        "always_value": "always",
        "errors": {},
        "plain_value": "plain",
    }
    assert initial.json()["deferredProps"] == {"activity": ["deferred_value"]}

    assert partial_only.json()["props"] == {
        "always_value": "always",
        "deferred_value": "deferred",
        "errors": {},
    }

    assert partial_except.json()["props"] == {
        "always_value": "always",
        "errors": {},
    }


def test_ship_rejects_mixing_inertia_and_widgets(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))
    ship.inertia()

    with pytest.raises(RuntimeError, match="cannot register widgets and Inertia pages"):
        ship.widget(path=Path("hello/widget.tsx"))


def _page_app(inertia, *, routes: list[Route]) -> Starlette:
    @asynccontextmanager
    async def lifespan(_: Starlette):
        async with inertia.lifespan(watch=None):
            yield

    return Starlette(
        lifespan=lifespan,
        middleware=[Middleware(SessionStateMiddleware)],
        routes=routes,
    )
