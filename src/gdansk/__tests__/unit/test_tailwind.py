from __future__ import annotations

from gdansk.tailwind import Tailwind


def test_tailwind_defaults_enabled():
    assert Tailwind().enabled is True


def test_tailwind_can_be_disabled():
    assert Tailwind(enabled=False).enabled is False
