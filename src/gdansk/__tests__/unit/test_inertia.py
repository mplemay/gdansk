from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from gdansk import Always, Defer, Merge, Metadata, Once, OptionalProp, Scroll, Ship, Vite
from gdansk.__tests__.unit.conftest import SessionStateMiddleware, write_page_manifest


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
    inertia = ship.inertia()
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


def test_inertia_renders_custom_root_id_in_html_shell(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    inertia = ship.inertia(root_id="custom-root")
    page = {
        "component": "/",
        "flash": {},
        "props": {
            "errors": {},
        },
        "url": "/",
        "version": inertia.version(),
    }

    html = inertia.render_html(metadata=None, page=page)

    assert '<script data-page="custom-root" type="application/json">' in html
    assert '<div id="custom-root"></div>' in html


def test_inertia_json_response_has_expected_page_shape(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    inertia = ship.inertia()

    async def home(request: Request):
        page = ship.page(request)
        page.share(shared=lambda: "shared")
        return await page.render("/", {"message": lambda: "hello"})

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.status_code == 200
    assert response.headers["X-Inertia"] == "true"
    assert response.headers["Vary"] == "X-Inertia"
    assert response.json() == {
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


def test_inertia_returns_409_for_stale_asset_versions(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def home(request: Request):
        page = ship.page(request)
        return await page.render("/", {})

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
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

    async def home(request: Request):
        page = ship.page(request)
        return await page.render(
            "/",
            {
                "always_value": Always(value=lambda: "always"),
                "deferred_value": Defer(value=lambda: "deferred", group="activity"),
                "optional_value": OptionalProp(value=lambda: "optional"),
                "plain_value": lambda: "plain",
            },
        )

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        partial_only = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "deferred_value",
            },
        )
        partial_except = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
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


def test_inertia_supports_once_props_reuse_and_refresh(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    calls: list[str] = []

    def expensive() -> str:
        value = f"value-{len(calls) + 1}"
        calls.append(value)
        return value

    async def home(request: Request):
        page = ship.page(request)
        return await page.render("/", {"expensive": Once(value=expensive)})

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        skipped = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Except-Once-Props": "expensive",
            },
        )
        refreshed = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Except-Once-Props": "expensive",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "expensive",
            },
        )

    assert initial.json()["props"] == {
        "errors": {},
        "expensive": "value-1",
    }
    assert initial.json()["onceProps"] == {
        "expensive": {
            "expiresAt": None,
            "prop": "expensive",
        },
    }

    assert skipped.json()["props"] == {"errors": {}}
    assert skipped.json()["onceProps"] == initial.json()["onceProps"]

    assert refreshed.json()["props"] == {
        "errors": {},
        "expensive": "value-2",
    }
    assert calls == ["value-1", "value-2"]


def test_inertia_once_props_support_custom_keys_expiration_and_fresh(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    calls: list[str] = []

    def record(name: str) -> str:
        calls.append(name)
        return name

    async def home(request: Request):
        page = ship.page(request)
        return await page.render(
            "/",
            {
                "aliased": Once(value=lambda: record("aliased"), key="shared-cache"),
                "expired": Once(value=lambda: record("expired"), expires_at=timedelta(seconds=-1)),
                "fresh_value": Once(value=lambda: record("fresh"), fresh=True),
                "stale": Once(value=lambda: record("stale")),
            },
        )

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Except-Once-Props": "shared-cache,expired,fresh_value,stale",
            },
        )

    assert response.json()["props"] == {
        "errors": {},
        "expired": "expired",
        "fresh_value": "fresh",
    }
    assert response.json()["onceProps"].keys() == {"shared-cache", "expired", "fresh_value", "stale"}
    assert response.json()["onceProps"]["shared-cache"]["prop"] == "aliased"
    assert calls == ["expired", "fresh"]


def test_inertia_partial_reload_supports_nested_only_and_except_paths(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def home(request: Request):
        page = ship.page(request)
        return await page.render(
            "/",
            {
                "auth": lambda: {
                    "notifications": ["ping"],
                    "roles": ["admin"],
                    "user": {"name": "Ada"},
                },
            },
        )

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        only_response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "auth.notifications",
            },
        )
        except_response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Except": "auth.notifications",
            },
        )

    assert only_response.json()["props"] == {
        "auth": {"notifications": ["ping"]},
        "errors": {},
    }
    assert except_response.json()["props"] == {
        "auth": {
            "roles": ["admin"],
            "user": {"name": "Ada"},
        },
        "errors": {},
    }


def test_inertia_emits_merge_metadata_and_respects_resets(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def home(request: Request):
        page = ship.page(request)
        return await page.render(
            "/",
            {
                "announcements": Merge(
                    value=[{"id": 2, "title": "Launch"}],
                    match_on="id",
                    mode="prepend",
                ),
                "conversation": Merge(
                    value={
                        "messages": [{"body": "Hello", "id": 3}],
                    },
                    deep=True,
                    match_on="messages.id",
                ),
                "users": Merge(value=[{"id": 1, "name": "Ada"}], match_on="id"),
            },
        )

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        reset = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "announcements,conversation,users",
                "X-Inertia-Reset": "conversation,users",
            },
        )

    assert initial.json()["mergeProps"] == ["users"]
    assert initial.json()["prependProps"] == ["announcements"]
    assert initial.json()["deepMergeProps"] == ["conversation"]
    assert initial.json()["matchPropsOn"] == [
        "announcements.id",
        "conversation.messages.id",
        "users.id",
    ]

    assert "mergeProps" not in reset.json()
    assert reset.json()["prependProps"] == ["announcements"]
    assert "deepMergeProps" not in reset.json()
    assert reset.json()["matchPropsOn"] == ["announcements.id"]


def test_inertia_rejects_deep_prepend_merge_props() -> None:
    with pytest.raises(ValueError, match="Deep merge props cannot use prepend mode"):
        Merge(value={}, deep=True, mode="prepend")


def test_inertia_scroll_props_follow_merge_intent_and_reset(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def home(request: Request):
        page = ship.page(request)
        return await page.render(
            "/",
            {
                "feed": Scroll(
                    value={
                        "items": [{"id": 1, "title": "Update"}],
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
            },
        )

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        prepend_response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Infinite-Scroll-Merge-Intent": "prepend",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "feed",
            },
        )
        reset_response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "feed",
                "X-Inertia-Reset": "feed",
            },
        )
        partial_items_response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Data": "feed.items",
            },
        )
        except_pagination_response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "/",
                "X-Inertia-Partial-Except": "feed.pagination",
            },
        )

    expected_scroll_prop = {
        "currentPage": 2,
        "nextPage": 3,
        "pageName": "feed_page",
        "previousPage": 1,
        "reset": False,
    }
    assert initial.json()["mergeProps"] == ["feed.items"]
    assert initial.json()["scrollProps"] == {
        "feed": expected_scroll_prop,
    }

    assert prepend_response.json()["prependProps"] == ["feed.items"]
    assert "mergeProps" not in prepend_response.json()
    assert prepend_response.json()["scrollProps"]["feed"]["reset"] is False

    assert "mergeProps" not in reset_response.json()
    assert "prependProps" not in reset_response.json()
    assert reset_response.json()["scrollProps"]["feed"]["reset"] is True

    assert partial_items_response.json()["props"]["feed"] == {"items": [{"id": 1, "title": "Update"}]}
    assert partial_items_response.json()["scrollProps"]["feed"] == expected_scroll_prop

    assert except_pagination_response.status_code == 200
    assert except_pagination_response.json()["props"]["feed"] == {"items": [{"id": 1, "title": "Update"}]}
    assert except_pagination_response.json()["scrollProps"]["feed"] == expected_scroll_prop


def test_inertia_location_non_inertia_redirects_convert_unsafe_methods(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def jump(request: Request):
        page = ship.page(request)
        return page.location("/target")

    with TestClient(_page_app(ship, routes=[Route("/jump", jump, methods=["GET", "POST", "PUT", "PATCH"])])) as client:
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
    ship = Ship(vite=Vite(page_views_path))
    ship.inertia(encrypt_history=True)

    async def home(request: Request):
        page = ship.page(request)
        return await page.render("/", {"message": "Home"})

    async def cleared(request: Request):
        page = ship.page(request)
        page.clear_history()
        page.encrypt_history(enabled=False)
        return await page.render("/", {"message": "Cleared"})

    async def preserve(request: Request):
        page = ship.page(request)
        return page.redirect("/target", preserve_fragment=True)

    async def explicit_fragment(request: Request):
        page = ship.page(request)
        return page.redirect("/target#details")

    async def target(request: Request):
        page = ship.page(request)
        return await page.render("/", {"message": "Target"})

    routes = [
        Route("/", home),
        Route("/cleared", cleared),
        Route("/preserve", preserve, methods=["POST"]),
        Route("/fragment", explicit_fragment, methods=["POST"]),
        Route("/target", target),
    ]

    with TestClient(_page_app(ship, routes=routes)) as client:
        initial = client.get("/", headers={"X-Inertia": "true"})
        cleared_response = client.get("/cleared", headers={"X-Inertia": "true"})
        preserve_response = client.post("/preserve", headers={"X-Inertia": "true"}, follow_redirects=False)
        after_preserve = client.get("/target", headers={"X-Inertia": "true"})
        after_preserve_again = client.get("/target", headers={"X-Inertia": "true"})
        explicit = client.post("/fragment", headers={"X-Inertia": "true"}, follow_redirects=False)

    assert initial.json()["encryptHistory"] is True

    assert cleared_response.json()["clearHistory"] is True
    assert "encryptHistory" not in cleared_response.json()

    assert preserve_response.status_code == 303
    assert preserve_response.headers["location"] == "/target"
    assert after_preserve.json()["preserveFragment"] is True
    assert "preserveFragment" not in after_preserve_again.json()

    assert explicit.status_code == 409
    assert explicit.headers["Vary"] == "X-Inertia"
    assert explicit.headers["X-Inertia-Redirect"] == "/target#details"


def test_inertia_normalizes_nested_component_keys(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def home(request: Request):
        page = ship.page(request)
        return await page.render("/dashboard/reports/", {})

    with TestClient(_page_app(ship, routes=[Route("/", home)])) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/reports"


def test_inertia_rejects_invalid_component_keys(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    async def home(request: Request):
        page = ship.page(request)
        return await page.render("../secret", {})

    with (
        TestClient(_page_app(ship, routes=[Route("/", home)])) as client,
        pytest.raises(ValueError, match="component"),
    ):
        client.get("/", headers={"X-Inertia": "true"})


def test_ship_page_uses_custom_inertia_configuration(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))
    request = _request(path="/")

    ship.inertia(root_id="custom-root", version="custom-version", encrypt_history=True)
    page = ship.page(request)

    assert page._app.root_id == "custom-root"
    assert page._app.version() == "custom-version"
    assert page._app.default_encrypt_history is True


def test_ship_rejects_mixing_inertia_and_widgets(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))
    ship.inertia()

    with pytest.raises(RuntimeError, match="cannot register widgets and Inertia pages"):
        ship.widget(path=Path("hello/widget.tsx"))


def _page_app(ship: Ship, *, routes: list[Route]) -> Starlette:
    @asynccontextmanager
    async def lifespan(_: Starlette):
        async with ship.lifespan(watch=None):
            yield

    return Starlette(
        lifespan=lifespan,
        middleware=[Middleware(SessionStateMiddleware)],
        routes=routes,
    )


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
