from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from gdansk import Ship, Vite
from gdansk.__tests__.unit.conftest import write_page_manifest
from gdansk.inertia import Always, Defer, Merge, Once, OptionalProp, Scroll
from gdansk.inertia.__tests__.unit import helpers

if TYPE_CHECKING:
    from pathlib import Path


def test_inertia_partial_reload_respects_optional_always_and_deferred_props(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path))
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.PartialReloadPageProps:
        return helpers.PartialReloadPageProps(
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

    helpers._assert_released_v3_page_payload(initial_page)
    helpers._assert_released_v3_page_payload(partial_only_page)
    helpers._assert_released_v3_page_payload(partial_except_page)

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
    app = helpers._page_app(ship)
    calls: list[str] = []

    def expensive() -> str:
        value = f"value-{len(calls) + 1}"
        calls.append(value)
        return value

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.OncePageProps:
        return helpers.OncePageProps(expensive=Once(value=expensive))

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

    helpers._assert_released_v3_page_payload(initial_page)
    helpers._assert_released_v3_page_payload(skipped_page)
    helpers._assert_released_v3_page_payload(refreshed_page)

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
    app = helpers._page_app(ship)
    calls: list[str] = []

    def record(name: str) -> str:
        calls.append(name)
        return name

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.OnceOptionsPageProps:
        return helpers.OnceOptionsPageProps(
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
    helpers._assert_released_v3_page_payload(page_payload)
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
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.NestedAuthPageProps:
        return helpers.NestedAuthPageProps(
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

    helpers._assert_released_v3_page_payload(only_page)
    helpers._assert_released_v3_page_payload(except_page)

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
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.MergeMetadataPageProps:
        return helpers.MergeMetadataPageProps(
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

    helpers._assert_released_v3_page_payload(initial_page)
    helpers._assert_released_v3_page_payload(reset_page)

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
    app = helpers._page_app(ship)

    @app.get("/")
    @ship.page("/")
    async def home() -> helpers.ScrollPageProps:
        return helpers.ScrollPageProps(
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

    helpers._assert_released_v3_page_payload(initial_page)
    helpers._assert_released_v3_page_payload(prepend_page)
    helpers._assert_released_v3_page_payload(reset_page)
    helpers._assert_released_v3_page_payload(partial_items_page)
    helpers._assert_released_v3_page_payload(except_pagination_page)

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
