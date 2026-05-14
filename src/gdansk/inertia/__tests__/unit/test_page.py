from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import Depends
from pydantic import ValidationError
from starlette.testclient import TestClient

from gdansk import Ship, Vite
from gdansk.__tests__.unit.conftest import write_page_manifest
from gdansk.inertia import Inertia, InertiaPage
from gdansk.inertia.__tests__.unit import helpers

if TYPE_CHECKING:
    from pathlib import Path


def test_inertia_json_response_has_expected_page_shape(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    inertia = ship._ensure_inertia_app()
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage = Depends(ship.page)) -> helpers.LazyMessagePageProps:
        page.share(shared=lambda: "shared")
        return helpers.LazyMessagePageProps(message=lambda: "hello")

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()

    assert response.status_code == 200
    assert response.headers["X-Inertia"] == "true"
    assert response.headers["Vary"] == "X-Inertia"
    helpers._assert_released_v3_page_payload(page_payload)
    assert page_payload == {
        "component": "/",
        "flash": {},
        "props": {
            "errors": {},
            "message": "hello",
            "shared": "shared",
        },
        "sharedProps": ["shared"],
        "url": "/",
        "version": inertia.version(),
    }


def test_inertia_share_accepts_typed_model_mapping_and_keyword_updates(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=helpers.SharedPageProps))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage[helpers.SharedPageProps] = Depends(ship.page)) -> helpers.EmptyPageProps:
        page.share(helpers.SharedPageProps(headline="Shared headline"))
        page.share({"sessionToken": "abc123"})
        page.share(summary="Keyword summary")
        page.share(helpers.SharedPageProps(summary="Updated summary"))
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()

    helpers._assert_released_v3_page_payload(page_payload)
    assert page_payload["props"] == {
        "errors": {},
        "headline": "Shared headline",
        "sessionToken": "abc123",
        "summary": "Updated summary",
    }
    assert page_payload["sharedProps"] == ["headline", "sessionToken", "summary"]


def test_inertia_typed_share_validates_partial_updates(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=helpers.SharedPageProps))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage[helpers.SharedPageProps] = Depends(ship.page)) -> helpers.EmptyPageProps:
        page.share(headline="x")
        return helpers.EmptyPageProps()

    with (
        TestClient(app) as client,
        pytest.raises(ValidationError, match="at least 2"),
    ):
        client.get("/", headers={"X-Inertia": "true"})


def test_inertia_route_props_override_typed_shared_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=helpers.SharedPageProps))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage[helpers.SharedPageProps] = Depends(ship.page)) -> dict[str, object]:
        page.share(headline="Shared headline", summary="Shared summary")
        return {"headline": "Route headline"}

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()

    helpers._assert_released_v3_page_payload(page_payload)
    assert page_payload["props"] == {
        "errors": {},
        "headline": "Route headline",
        "summary": "Shared summary",
    }
    assert page_payload["sharedProps"] == ["summary"]


def test_inertia_partial_reload_preserves_typed_shared_props_metadata(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=helpers.SharedPageProps))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage[helpers.SharedPageProps] = Depends(ship.page)) -> helpers.MessagePageProps:
        page.share(headline="Shared headline", summary="Shared summary")
        return helpers.MessagePageProps(message="Route message")

    with TestClient(app) as client:
        response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "message",
            },
        )

    page_payload = response.json()

    helpers._assert_released_v3_page_payload(page_payload)
    assert page_payload["props"] == {
        "errors": {},
        "message": "Route message",
    }
    assert page_payload["sharedProps"] == ["headline", "summary"]


def test_inertia_share_once_accepts_typed_model_updates(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(props=helpers.SharedPageProps))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage[helpers.SharedPageProps] = Depends(ship.page)) -> helpers.EmptyPageProps:
        page.share_once(helpers.SharedPageProps(session_token="token-123"))
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()

    helpers._assert_released_v3_page_payload(page_payload)
    assert page_payload["props"] == {
        "errors": {},
        "sessionToken": "token-123",
    }
    assert page_payload["onceProps"] == {
        "sessionToken": {
            "expiresAt": None,
            "prop": "sessionToken",
        },
    }
    assert page_payload["sharedProps"] == ["sessionToken"]


def test_inertia_omits_default_false_and_client_owned_v3_fields(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.EmptyPageProps:
        return helpers.EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()
    helpers._assert_released_v3_page_payload(page_payload)
    assert page_payload == {
        "component": "/",
        "flash": {},
        "props": {
            "errors": {},
        },
        "url": "/",
        "version": ship._ensure_inertia_app().version(),
    }


def test_inertia_rejects_client_owned_deferred_prop(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> dict[str, object]:
        return {"deferred": {"default": ["stats"]}}

    with (
        TestClient(app) as client,
        pytest.raises(RuntimeError, match=r"props\.deferred"),
    ):
        client.get("/", headers={"X-Inertia": "true"})


def test_inertia_location_non_inertia_redirects_convert_unsafe_methods(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.api_route("/jump", methods=["GET", "POST", "PUT", "PATCH"])
    async def jump(page: InertiaPage = Depends(ship.page)):
        return page.location("/target")

    with TestClient(app) as client:
        get_response = client.get("/jump", follow_redirects=False)
        post_response = client.post("/jump", follow_redirects=False)
        put_response = client.put("/jump", follow_redirects=False)
        patch_response = client.patch("/jump", follow_redirects=False)

    assert get_response.status_code == 307
    assert post_response.status_code == 303
    assert put_response.status_code == 303
    assert patch_response.status_code == 303
    assert get_response.headers["location"] == "/target"
    assert post_response.headers["location"] == "/target"
    assert put_response.headers["location"] == "/target"
    assert patch_response.headers["location"] == "/target"


def test_inertia_supports_history_flags_and_fragment_redirects(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(encrypt_history=True))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.MessagePageProps:
        return helpers.MessagePageProps(message="Home")

    @app.get("/cleared")
    @ship.page("/")
    async def cleared(page: InertiaPage = Depends(ship.page)) -> helpers.MessagePageProps:
        page.clear_history()
        page.encrypt_history(enabled=False)
        return helpers.MessagePageProps(message="Cleared")

    @app.post("/preserve")
    async def preserve(page: InertiaPage = Depends(ship.page)):
        return page.redirect("/target", preserve_fragment=True)

    @app.post("/fragment")
    async def explicit_fragment(page: InertiaPage = Depends(ship.page)):
        return page.redirect("/target#details")

    @app.get("/target")
    @ship.page("/")
    async def target() -> helpers.MessagePageProps:
        return helpers.MessagePageProps(message="Target")

    with TestClient(app) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        cleared_response = client.get("/cleared", headers={"X-Inertia": "true"})
        preserve_response = client.post("/preserve", headers={"X-Inertia": "true"}, follow_redirects=False)
        after_preserve = client.get("/target", headers={"X-Inertia": "true"})
        after_preserve_again = client.get("/target", headers={"X-Inertia": "true"})
        explicit = client.post("/fragment", headers={"X-Inertia": "true"}, follow_redirects=False)

    initial_page = initial.json()
    cleared_page = cleared_response.json()
    after_preserve_page = after_preserve.json()
    after_preserve_again_page = after_preserve_again.json()

    helpers._assert_released_v3_page_payload(initial_page)
    helpers._assert_released_v3_page_payload(cleared_page)
    helpers._assert_released_v3_page_payload(after_preserve_page)
    helpers._assert_released_v3_page_payload(after_preserve_again_page)

    assert initial_page["encryptHistory"] is True

    assert cleared_page["clearHistory"] is True
    assert "encryptHistory" not in cleared_page

    assert preserve_response.status_code == 303
    assert preserve_response.headers["location"] == "/target"
    assert after_preserve_page["preserveFragment"] is True
    assert "preserveFragment" not in after_preserve_again_page

    assert explicit.status_code == 409
    assert explicit.headers["Vary"] == "X-Inertia"
    assert explicit.headers["X-Inertia-Redirect"] == "/target#details"


def test_inertia_page_has_no_public_render_api() -> None:
    assert not hasattr(InertiaPage, "render")


def test_inertia_decorator_rejects_multiple_page_dependencies(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(
        first_page: InertiaPage = Depends(ship.page),
        second_page: InertiaPage = Depends(ship.page),
    ) -> helpers.EmptyPageProps:
        first_page.share(first=True)
        second_page.share(second=True)
        return helpers.EmptyPageProps()

    with (
        TestClient(app) as client,
        pytest.raises(RuntimeError, match="at most one InertiaPage"),
    ):
        client.get("/", headers={"X-Inertia": "true"})


def test_inertia_decorator_rejects_page_from_different_app(page_views_path: Path):
    first_ship = Ship(vite=Vite(page_views_path))
    second_ship = Ship(vite=Vite(page_views_path))
    request = helpers._request(path="/")
    page = second_ship.page(request)

    with pytest.raises(RuntimeError, match="different Inertia app"):
        first_ship._ensure_inertia_app()._route_page(args=(page,), kwargs={}, request=request)


def test_inertia_decorator_rejects_page_from_different_request(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))
    request = helpers._request(path="/")
    page = ship.page(helpers._request(path="/other"))

    with pytest.raises(RuntimeError, match="different request"):
        ship._ensure_inertia_app()._route_page(args=(page,), kwargs={}, request=request)
