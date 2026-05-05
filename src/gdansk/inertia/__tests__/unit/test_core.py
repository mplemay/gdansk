from __future__ import annotations

from json import loads
from pathlib import Path

import pytest
from fastapi import Depends
from starlette.testclient import TestClient

from gdansk import Metadata, Ship, Vite
from gdansk.__tests__.unit.conftest import write_page_manifest
from gdansk.inertia import InertiaPage, InertiaResponse  # noqa: TC001
from gdansk.inertia.__tests__.unit import helpers


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
    inertia = ship._ensure_inertia_app()
    page = {
        "component": "/",
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
    inertia = ship._ensure_inertia_app()
    page = {
        "component": "/",
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
    assert '<script type="module" src="http://127.0.0.1:5173/@gdansk/pages/app.tsx"></script>' in html
    assert '<link rel="stylesheet"' not in html


def test_inertia_runtime_dependency_targets_released_v3() -> None:
    package_json_path = Path(__file__).resolve().parents[5] / "packages/vite/package.json"
    package_json = loads(package_json_path.read_text(encoding="utf-8"))

    assert package_json["dependencies"]["@inertiajs/react"] == "3.0.3"


def test_inertia_returns_409_for_stale_asset_versions(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.EmptyPageProps:
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
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


def test_inertia_page_decorator_renders_none_as_empty_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page()
    async def home() -> None:
        return None

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page = response.json()

    helpers._assert_released_v3_page_payload(page)
    assert page["props"] == {"errors": {}}


def test_inertia_page_decorator_accepts_props_response_or_none_return(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page()
    async def home(
        mode: str = "props",
        page: InertiaPage = Depends(ship.page),
    ) -> helpers.HomeProps | InertiaResponse | None:
        if mode == "jump":
            return page.location("/#activity")
        if mode == "empty":
            return None
        return helpers.HomeProps(message="Home")

    with TestClient(app) as client:
        props_response = client.get("/", headers={"X-Inertia": "true"})
        none_response = client.get("/?mode=empty", headers={"X-Inertia": "true"})
        location_response = client.get("/?mode=jump", headers={"X-Inertia": "true"}, follow_redirects=False)

    props_page = props_response.json()
    none_page = none_response.json()

    helpers._assert_released_v3_page_payload(props_page)
    helpers._assert_released_v3_page_payload(none_page)

    assert props_page["props"]["message"] == "Home"
    assert none_page["props"] == {"errors": {}}
    assert location_response.status_code == 409
    assert location_response.headers["Vary"] == "X-Inertia"
    assert location_response.headers["X-Inertia-Location"] == "/#activity"


def test_inertia_page_decorator_infers_root_component(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page()
    async def home() -> helpers.EmptyPageProps:
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "/"


def test_inertia_page_decorator_infers_nested_route_component(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/dashboard/reports")
    @ship.page()
    async def reports() -> helpers.EmptyPageProps:
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/dashboard/reports", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/reports"


def test_inertia_page_decorator_prefers_route_template_for_dynamic_components(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/dashboard/{report_id}")
    @ship.page()
    async def report(report_id: str) -> helpers.EmptyPageProps:
        assert report_id == "weekly"
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/dashboard/weekly", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/{report_id}"


def test_inertia_normalizes_nested_component_keys(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/dashboard/reports/")
    async def home() -> helpers.EmptyPageProps:
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/reports"


def test_inertia_rejects_invalid_component_keys(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    with pytest.raises(ValueError, match="component"):
        ship.page("../secret")
