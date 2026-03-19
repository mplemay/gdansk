"""Compatibility shim for the relocated PostCSS plugin."""

from gdansk.plugins.postcss import PostCSS, PostCSSError

__all__ = ["PostCSS", "PostCSSError"]
