from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from gdansk import Ship, Vite
from gdansk.__tests__.unit.conftest import write_page_manifest
from gdansk.inertia import Inertia
from gdansk.inertia.__tests__.unit import helpers


def test_inertia_renders_custom_root_id_in_html_shell(page_views_path: Path):
    write_page_manifest(page_views_path)
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia(id="custom-root"))
    inertia = ship._ensure_inertia_app()
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


@pytest.mark.parametrize("id_value", ["", "   "])
def test_inertia_rejects_empty_id(id_value: str) -> None:
    with pytest.raises(ValueError, match="Inertia id"):
        Inertia(id=id_value)


def test_inertia_accepts_shared_props_model(page_views_path: Path):
    ship = Ship(
        vite=Vite(page_views_path),
        inertia=Inertia(props=helpers.SharedPageProps),
    )
    request = helpers._request(path="/")

    page = ship.page(request)

    assert page._app.shared_props_model is helpers.SharedPageProps


@pytest.mark.parametrize("props", [dict, object()])
def test_inertia_rejects_invalid_shared_props_model(props: object) -> None:
    with pytest.raises(TypeError, match="props model"):
        Inertia(props=cast("Any", props))


def test_ship_page_uses_custom_inertia_configuration(page_views_path: Path):
    ship = Ship(
        vite=Vite(page_views_path),
        inertia=Inertia(id="custom-root", version="custom-version", encrypt_history=True),
    )
    request = helpers._request(path="/")

    page = ship.page(request)

    assert page._app.root_id == "custom-root"
    assert page._app.version() == "custom-version"
    assert page._app.default_encrypt_history is True


def test_ship_rejects_mixing_inertia_and_widgets(page_views_path: Path):
    ship = Ship(vite=Vite(page_views_path), inertia=Inertia())

    with pytest.raises(RuntimeError, match="cannot register widgets and Inertia pages"):
        ship.widget(path=Path("hello/widget.tsx"))
