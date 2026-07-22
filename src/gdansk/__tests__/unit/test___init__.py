from __future__ import annotations

from importlib import import_module, reload

import pytest

import gdansk


def test_package_emits_deprecation_warning() -> None:
    with pytest.warns(DeprecationWarning, match=r"deprecated.*belgie"):
        reload(gdansk)


def test_top_level_exports_do_not_include_belgie_runtime_surface() -> None:
    hidden_names = {
        "GdanskError",
        "GdanskJavaScriptError",
        "GdanskModuleError",
        "GdanskRuntimeError",
        "PackageInstallResult",
        "PackageUpdateChange",
        "PackageUpdateResult",
        "Runtime",
        "RuntimeOptions",
        "Script",
        "ainstall_packages",
        "alock_packages",
        "aupdate_packages",
        "install_packages",
        "lock_packages",
        "update_packages",
    }

    assert hidden_names.isdisjoint(gdansk.__all__)
    for name in hidden_names:
        assert not hasattr(gdansk, name)


def test_top_level_exports_gdansk_surface() -> None:
    assert {
        "FileParam",
        "JsonArray",
        "JsonInput",
        "JsonObject",
        "JsonOutput",
        "JsonPrimitive",
        "Metadata",
        "Ship",
        "Vite",
        "WidgetMeta",
    } <= set(gdansk.__all__)


def test_core_compatibility_module_is_not_available() -> None:
    with pytest.raises(ModuleNotFoundError):
        import_module("gdansk._core")
