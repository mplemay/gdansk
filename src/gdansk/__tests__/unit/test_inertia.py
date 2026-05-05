from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from json import loads
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from starlette.requests import Request
from starlette.testclient import TestClient

from gdansk import Always, Defer, InertiaPage, Merge, Metadata, Once, OptionalProp, Scroll, Ship, Vite
from gdansk.__tests__.unit.conftest import SessionStateMiddleware, write_page_manifest


class EmptyPageProps(BaseModel):
    pass


class LazyMessagePageProps(BaseModel):
    message: object


class MessagePageProps(BaseModel):
    message: str


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
    announcements: Merge[list[dict[str, object]]]
    conversation: Merge[dict[str, object]]
    users: Merge[list[dict[str, object]]]


class ScrollPageProps(BaseModel):
    feed: Scroll[dict[str, object]]


_V3_REQUIRED_PAGE_KEYS: Final[frozenset[str]] = frozenset({"component", "flash", "props", "url", "version"})
_V3_CLIENT_OWNED_PAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "initialDeferredProps",
        "optimisticUpdatedAt",
        "rememberedState",
    },
)
_UNSUPPORTED_3X_PAGE_KEYS: Final[frozenset[str]] = frozenset({"rescuedProps"})


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
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(page: InertiaPage = Depends(ship.page)) -> LazyMessagePageProps:
        page.share(shared=lambda: "shared")
        return LazyMessagePageProps(message=lambda: "hello")

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()

    assert response.status_code == 200
    assert response.headers["X-Inertia"] == "true"
    assert response.headers["Vary"] == "X-Inertia"
    _assert_released_v3_page_payload(page_payload)
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


def test_inertia_omits_default_false_and_client_owned_v3_fields(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> EmptyPageProps:
        return EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    page_payload = response.json()
    _assert_released_v3_page_payload(page_payload)
    assert page_payload == {
        "component": "/",
        "flash": {},
        "props": {
            "errors": {},
        },
        "url": "/",
        "version": ship.inertia().version(),
    }


def test_inertia_rejects_client_owned_deferred_prop(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> dict[str, object]:
        return {"deferred": {"default": ["stats"]}}

    with (
        TestClient(app) as client,
        pytest.raises(RuntimeError, match=r"props\.deferred"),
    ):
        client.get("/", headers={"X-Inertia": "true"})


def test_inertia_runtime_dependency_targets_released_v3() -> None:
    package_json_path = Path(__file__).resolve().parents[4] / "packages/vite/package.json"
    package_json = loads(package_json_path.read_text(encoding="utf-8"))

    assert package_json["dependencies"]["@inertiajs/react"] == "3.0.3"


def test_inertia_returns_409_for_stale_asset_versions(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> EmptyPageProps:
        return EmptyPageProps()

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


def test_inertia_partial_reload_respects_optional_always_and_deferred_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> PartialReloadPageProps:
        return PartialReloadPageProps(
            always_value=Always(value=lambda: "always"),
            deferred_value=Defer(value=lambda: "deferred", group="activity"),
            optional_value=OptionalProp(value=lambda: "optional"),
            plain_value=lambda: "plain",
        )

    with TestClient(app) as client:
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

    initial_page = initial.json()
    partial_only_page = partial_only.json()
    partial_except_page = partial_except.json()

    _assert_released_v3_page_payload(initial_page)
    _assert_released_v3_page_payload(partial_only_page)
    _assert_released_v3_page_payload(partial_except_page)

    assert initial_page["props"] == {
        "always_value": "always",
        "errors": {},
        "plain_value": "plain",
    }
    assert initial_page["deferredProps"] == {"activity": ["deferred_value"]}

    assert partial_only_page["props"] == {
        "always_value": "always",
        "deferred_value": "deferred",
        "errors": {},
    }

    assert partial_except_page["props"] == {
        "always_value": "always",
        "errors": {},
    }


def test_inertia_supports_once_props_reuse_and_refresh(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)
    calls: list[str] = []

    def expensive() -> str:
        value = f"value-{len(calls) + 1}"
        calls.append(value)
        return value

    @app.get("/")
    @ship.page("/")
    async def home() -> OncePageProps:
        return OncePageProps(expensive=Once(value=expensive))

    with TestClient(app) as client:
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

    initial_page = initial.json()
    skipped_page = skipped.json()
    refreshed_page = refreshed.json()

    _assert_released_v3_page_payload(initial_page)
    _assert_released_v3_page_payload(skipped_page)
    _assert_released_v3_page_payload(refreshed_page)

    assert initial_page["props"] == {
        "errors": {},
        "expensive": "value-1",
    }
    assert initial_page["onceProps"] == {
        "expensive": {
            "expiresAt": None,
            "prop": "expensive",
        },
    }

    assert skipped_page["props"] == {"errors": {}}
    assert skipped_page["onceProps"] == initial_page["onceProps"]

    assert refreshed_page["props"] == {
        "errors": {},
        "expensive": "value-2",
    }
    assert calls == ["value-1", "value-2"]


def test_inertia_once_props_support_custom_keys_expiration_and_fresh(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)
    calls: list[str] = []

    def record(name: str) -> str:
        calls.append(name)
        return name

    @app.get("/")
    @ship.page("/")
    async def home() -> OnceOptionsPageProps:
        return OnceOptionsPageProps(
            aliased=Once(value=lambda: record("aliased"), key="shared-cache"),
            expired=Once(value=lambda: record("expired"), expires_at=timedelta(seconds=-1)),
            fresh_value=Once(value=lambda: record("fresh"), fresh=True),
            stale=Once(value=lambda: record("stale")),
        )

    with TestClient(app) as client:
        response = client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Except-Once-Props": "shared-cache,expired,fresh_value,stale",
            },
        )

    page_payload = response.json()
    _assert_released_v3_page_payload(page_payload)
    assert page_payload["props"] == {
        "errors": {},
        "expired": "expired",
        "fresh_value": "fresh",
    }
    assert page_payload["onceProps"].keys() == {"shared-cache", "expired", "fresh_value", "stale"}
    assert page_payload["onceProps"]["shared-cache"]["prop"] == "aliased"
    assert calls == ["expired", "fresh"]


def test_inertia_partial_reload_supports_nested_only_and_except_paths(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> NestedAuthPageProps:
        return NestedAuthPageProps(
            auth=lambda: {
                "notifications": ["ping"],
                "roles": ["admin"],
                "user": {"name": "Ada"},
            },
        )

    with TestClient(app) as client:
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

    only_page = only_response.json()
    except_page = except_response.json()

    _assert_released_v3_page_payload(only_page)
    _assert_released_v3_page_payload(except_page)

    assert only_page["props"] == {
        "auth": {"notifications": ["ping"]},
        "errors": {},
    }
    assert except_page["props"] == {
        "auth": {
            "roles": ["admin"],
            "user": {"name": "Ada"},
        },
        "errors": {},
    }


def test_inertia_emits_merge_metadata_and_respects_resets(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> MergeMetadataPageProps:
        return MergeMetadataPageProps(
            announcements=Merge(
                value=[{"id": 2, "title": "Launch"}],
                match_on="id",
                mode="prepend",
            ),
            conversation=Merge(
                value={
                    "messages": [{"body": "Hello", "id": 3}],
                },
                deep=True,
                match_on="messages.id",
            ),
            users=Merge(value=[{"id": 1, "name": "Ada"}], match_on="id"),
        )

    with TestClient(app) as client:
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

    initial_page = initial.json()
    reset_page = reset.json()

    _assert_released_v3_page_payload(initial_page)
    _assert_released_v3_page_payload(reset_page)

    assert initial_page["mergeProps"] == ["users"]
    assert initial_page["prependProps"] == ["announcements"]
    assert initial_page["deepMergeProps"] == ["conversation"]
    assert initial_page["matchPropsOn"] == [
        "announcements.id",
        "conversation.messages.id",
        "users.id",
    ]

    assert "mergeProps" not in reset_page
    assert reset_page["prependProps"] == ["announcements"]
    assert "deepMergeProps" not in reset_page
    assert reset_page["matchPropsOn"] == ["announcements.id"]


def test_inertia_rejects_deep_prepend_merge_props() -> None:
    with pytest.raises(ValueError, match="Deep merge props cannot use prepend mode"):
        Merge(value={}, deep=True, mode="prepend")


def test_inertia_scroll_props_follow_merge_intent_and_reset(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> ScrollPageProps:
        return ScrollPageProps(
            feed=Scroll(
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
        )

    with TestClient(app) as client:
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

    initial_page = initial.json()
    prepend_page = prepend_response.json()
    reset_page = reset_response.json()
    partial_items_page = partial_items_response.json()
    except_pagination_page = except_pagination_response.json()

    _assert_released_v3_page_payload(initial_page)
    _assert_released_v3_page_payload(prepend_page)
    _assert_released_v3_page_payload(reset_page)
    _assert_released_v3_page_payload(partial_items_page)
    _assert_released_v3_page_payload(except_pagination_page)

    expected_scroll_prop = {
        "currentPage": 2,
        "nextPage": 3,
        "pageName": "feed_page",
        "previousPage": 1,
        "reset": False,
    }
    assert initial_page["mergeProps"] == ["feed.items"]
    assert initial_page["scrollProps"] == {
        "feed": expected_scroll_prop,
    }

    assert prepend_page["prependProps"] == ["feed.items"]
    assert "mergeProps" not in prepend_page
    assert prepend_page["scrollProps"]["feed"]["reset"] is False

    assert "mergeProps" not in reset_page
    assert "prependProps" not in reset_page
    assert reset_page["scrollProps"]["feed"]["reset"] is True

    assert partial_items_page["props"]["feed"] == {"items": [{"id": 1, "title": "Update"}]}
    assert partial_items_page["scrollProps"]["feed"] == expected_scroll_prop

    assert except_pagination_response.status_code == 200
    assert except_pagination_page["props"]["feed"] == {"items": [{"id": 1, "title": "Update"}]}
    assert except_pagination_page["scrollProps"]["feed"] == expected_scroll_prop


def test_inertia_location_non_inertia_redirects_convert_unsafe_methods(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

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
    ship = Ship(vite=Vite(page_views_path))
    ship.inertia(encrypt_history=True)
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> MessagePageProps:
        return MessagePageProps(message="Home")

    @app.get("/cleared")
    @ship.page("/")
    async def cleared(page: InertiaPage = Depends(ship.page)) -> MessagePageProps:
        page.clear_history()
        page.encrypt_history(enabled=False)
        return MessagePageProps(message="Cleared")

    @app.post("/preserve")
    async def preserve(page: InertiaPage = Depends(ship.page)):
        return page.redirect("/target", preserve_fragment=True)

    @app.post("/fragment")
    async def explicit_fragment(page: InertiaPage = Depends(ship.page)):
        return page.redirect("/target#details")

    @app.get("/target")
    @ship.page("/")
    async def target() -> MessagePageProps:
        return MessagePageProps(message="Target")

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

    _assert_released_v3_page_payload(initial_page)
    _assert_released_v3_page_payload(cleared_page)
    _assert_released_v3_page_payload(after_preserve_page)
    _assert_released_v3_page_payload(after_preserve_again_page)

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


def test_inertia_page_decorator_infers_root_component(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page()
    async def home() -> EmptyPageProps:
        return EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "/"


def test_inertia_page_decorator_infers_nested_route_component(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/dashboard/reports")
    @ship.page()
    async def reports() -> EmptyPageProps:
        return EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/dashboard/reports", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/reports"


def test_inertia_page_decorator_prefers_route_template_for_dynamic_components(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/dashboard/{report_id}")
    @ship.page()
    async def report(report_id: str) -> EmptyPageProps:
        assert report_id == "weekly"
        return EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/dashboard/weekly", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/{report_id}"


def test_inertia_normalizes_nested_component_keys(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/dashboard/reports/")
    async def home() -> EmptyPageProps:
        return EmptyPageProps()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Inertia": "true"})

    assert response.json()["component"] == "dashboard/reports"


def test_inertia_rejects_invalid_component_keys(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))

    with pytest.raises(ValueError, match="component"):
        ship.page("../secret")


def test_inertia_page_has_no_public_render_api() -> None:
    assert not hasattr(InertiaPage, "render")


def test_inertia_decorator_rejects_multiple_page_dependencies(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = _page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home(
        first_page: InertiaPage = Depends(ship.page),
        second_page: InertiaPage = Depends(ship.page),
    ) -> EmptyPageProps:
        first_page.share(first=True)
        second_page.share(second=True)
        return EmptyPageProps()

    with (
        TestClient(app) as client,
        pytest.raises(RuntimeError, match="at most one InertiaPage"),
    ):
        client.get("/", headers={"X-Inertia": "true"})


def test_inertia_decorator_rejects_page_from_different_app(page_views_path: Path):
    first_ship = Ship(vite=Vite(page_views_path))
    second_ship = Ship(vite=Vite(page_views_path))
    request = _request(path="/")
    page = second_ship.page(request)

    with pytest.raises(RuntimeError, match="different Inertia app"):
        first_ship.inertia()._route_page(args=(page,), kwargs={}, request=request)


def test_inertia_decorator_rejects_page_from_different_request(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path))
    request = _request(path="/")
    page = ship.page(_request(path="/other"))

    with pytest.raises(RuntimeError, match="different request"):
        ship.inertia()._route_page(args=(page,), kwargs={}, request=request)


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
