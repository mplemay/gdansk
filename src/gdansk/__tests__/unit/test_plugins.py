from __future__ import annotations

import importlib

import pytest

from gdansk import LightningCSS
from gdansk.plugins import LightningCSS as PackageLightningCSS


def test_lightningcss_exposes_expected_id():
    assert LightningCSS().id == "lightningcss"


def test_plugins_package_re_exports_lightningcss_only():
    assert PackageLightningCSS().id == LightningCSS().id


def test_public_package_no_longer_exports_postcss():
    module = importlib.import_module("gdansk")
    assert not hasattr(module, "PostCSS")


def test_plugins_package_no_longer_exports_postcss():
    module = importlib.import_module("gdansk.plugins")
    assert not hasattr(module, "PostCSS")


def test_experimental_postcss_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("gdansk.experimental.postcss")
