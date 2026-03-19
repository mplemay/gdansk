from gdansk import LightningCSS, PostCSS
from gdansk.experimental.postcss import PostCSS as LegacyPostCSS
from gdansk.plugins import LightningCSS as PackageLightningCSS, PostCSS as PackagePostCSS


def test_lightningcss_exposes_expected_id():
    assert LightningCSS().id == "lightningcss"


def test_plugins_package_re_exports_wrappers():
    assert PackageLightningCSS().id == LightningCSS().id
    assert PackagePostCSS().poll_interval_seconds == PostCSS().poll_interval_seconds


def test_experimental_postcss_shim_still_works():
    assert LegacyPostCSS().poll_interval_seconds == PostCSS().poll_interval_seconds
