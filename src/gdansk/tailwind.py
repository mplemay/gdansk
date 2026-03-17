"""Tailwind configuration primitives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class Tailwind:
    """Enables native Tailwind processing during bundling."""

    enabled: bool = True
