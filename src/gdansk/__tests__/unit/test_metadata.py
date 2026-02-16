from __future__ import annotations

from copy import deepcopy
from html import unescape

import pytest

from gdansk.metadata import merge_metadata
from gdansk.render import ENV


@pytest.mark.parametrize(
    (
        "base",
        "override",
        "expected",
        "expect_new_vs_base",
        "expect_new_vs_override",
    ),
    [
        pytest.param(None, None, None, False, False, id="none-none"),
        pytest.param(
            {"title": "Base", "openGraph": {"title": "Base OG"}},
            None,
            {"title": "Base", "openGraph": {"title": "Base OG"}},
            True,
            False,
            id="base-only-copy",
        ),
        pytest.param(
            None,
            {"title": "Override", "description": "Desc"},
            {"title": "Override", "description": "Desc"},
            False,
            True,
            id="override-only-copy",
        ),
        pytest.param(
            {"title": "Base", "description": "Base Desc", "keywords": ["a"]},
            {"title": "Override", "generator": "gdansk"},
            {"title": "Override", "description": "Base Desc", "keywords": ["a"], "generator": "gdansk"},
            True,
            True,
            id="both-shallow-merge",
        ),
        pytest.param(
            {"openGraph": {"title": "Base OG"}},
            {"openGraph": {"title": "Override OG"}},
            {"openGraph": {"title": "Override OG"}},
            True,
            True,
            id="override-replaces-top-level-key",
        ),
    ],
)
def test_merge_metadata(
    base,
    override,
    expected,
    expect_new_vs_base,
    expect_new_vs_override,
):
    base_snapshot = deepcopy(base)
    override_snapshot = deepcopy(override)

    result = merge_metadata(base, override)

    assert result == expected
    assert base == base_snapshot
    assert override == override_snapshot

    if expect_new_vs_base:
        assert result is not base
    if expect_new_vs_override:
        assert result is not override


@pytest.mark.parametrize(
    ("metadata", "expected_snippets", "unexpected_snippets"),
    [
        pytest.param(None, [], ["<title>", "<meta", "<link"], id="empty"),
        pytest.param(
            {"title": "Simple Title"},
            ["<title>Simple Title</title>"],
            [],
            id="title-string",
        ),
        pytest.param(
            {"title": {"absolute": "Absolute Title"}},
            ["<title>Absolute Title</title>"],
            [],
            id="title-template-absolute",
        ),
        pytest.param(
            {"title": {"default": "Fallback Title"}},
            ["<title>Fallback Title</title>"],
            [],
            id="title-template-default",
        ),
        pytest.param(
            {
                "description": "Page description",
                "applicationName": "App",
                "generator": "gdansk",
                "referrer": "origin",
                "colorScheme": "light dark",
                "creator": "Creator",
                "publisher": "Publisher",
                "abstract": "Abstract text",
                "category": "Docs",
                "classification": "Public",
            },
            [
                '<meta name="description" content="Page description" />',
                '<meta name="application-name" content="App" />',
                '<meta name="generator" content="gdansk" />',
                '<meta name="referrer" content="origin" />',
                '<meta name="color-scheme" content="light dark" />',
                '<meta name="creator" content="Creator" />',
                '<meta name="publisher" content="Publisher" />',
                '<meta name="abstract" content="Abstract text" />',
                '<meta name="category" content="Docs" />',
                '<meta name="classification" content="Public" />',
            ],
            [],
            id="base-scalar-meta-fields",
        ),
        pytest.param(
            {"keywords": ["alpha", "beta"]},
            ['<meta name="keywords" content="alpha, beta" />'],
            [],
            id="keywords-list",
        ),
        pytest.param(
            {
                "viewport": {
                    "width": "device-width",
                    "height": 900,
                    "initialScale": 1.0,
                    "minimumScale": 0.5,
                    "maximumScale": 3.0,
                    "userScalable": False,
                    "viewportFit": "cover",
                    "interactiveWidget": "resizes-content",
                },
            },
            [
                (
                    '<meta name="viewport" content="width=device-width, height=900, initial-scale=1.0, '
                    "minimum-scale=0.5, maximum-scale=3.0, user-scalable=no, viewport-fit=cover, "
                    'interactive-widget=resizes-content" />'
                ),
            ],
            [],
            id="viewport-object",
        ),
        pytest.param(
            {
                "themeColor": [
                    "#111111",
                    {"color": "#eeeeee", "media": "(prefers-color-scheme: light)"},
                ],
            },
            [
                '<meta name="theme-color" content="#111111" />',
                '<meta name="theme-color" content="#eeeeee" media="(prefers-color-scheme: light)" />',
            ],
            [],
            id="theme-color",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com/base",
                "authors": [{"name": "Ada", "url": "/authors/ada"}],
            },
            [
                '<meta name="author" content="Ada" />',
                '<link rel="author" href="https://example.com/authors/ada" />',
            ],
            [],
            id="authors",
        ),
        pytest.param(
            {
                "robots": {
                    "index": False,
                    "follow": True,
                    "maxSnippet": -1,
                    "googleBot": {"index": True, "follow": False, "maxImagePreview": "large"},
                },
            },
            [
                '<meta name="robots" content="noindex, follow, max-snippet:-1" />',
                '<meta name="googlebot" content="index, nofollow, max-image-preview:large" />',
            ],
            [],
            id="robots",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "alternates": {
                    "canonical": {"url": "/home", "title": "Home"},
                    "languages": {"en-US": [{"url": "/en", "title": "English"}]},
                    "media": {"(max-width: 600px)": "/mobile"},
                    "types": {"application/rss+xml": "/feed.xml"},
                },
            },
            [
                '<link rel="canonical" href="https://example.com/home" title="Home" />',
                '<link rel="alternate" href="https://example.com/en" hreflang="en-US" title="English" />',
                '<link rel="alternate" href="https://example.com/mobile" media="(max-width: 600px)" />',
                '<link rel="alternate" href="https://example.com/feed.xml" type="application/rss+xml" />',
            ],
            [],
            id="alternates",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "icons": {
                    "icon": [{"url": "/favicon.ico", "sizes": "32x32", "type": "image/x-icon"}],
                    "shortcut": "/shortcut.ico",
                    "apple": "/apple-touch-icon.png",
                    "other": [{"url": "/mask.svg", "rel": "mask-icon"}],
                },
            },
            [
                '<link rel="icon" href="https://example.com/favicon.ico" type="image/x-icon" sizes="32x32" />',
                '<link rel="shortcut icon" href="https://example.com/shortcut.ico" />',
                '<link rel="apple-touch-icon" href="https://example.com/apple-touch-icon.png" />',
                '<link rel="mask-icon" href="https://example.com/mask.svg" />',
            ],
            [],
            id="icons",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "openGraph": {
                    "title": "OG Title",
                    "description": "OG Description",
                    "url": "/post/1",
                    "siteName": "Site",
                    "locale": "en_US",
                    "type": "article",
                    "determiner": "the",
                    "countryName": "USA",
                    "ttl": 100,
                    "emails": ["a@example.com"],
                    "phoneNumbers": ["+12025550199"],
                    "faxNumbers": ["+12025550198"],
                    "alternateLocale": ["fr_FR"],
                    "images": [
                        {
                            "url": "/img.png",
                            "secureUrl": "/img-secure.png",
                            "width": 1200,
                            "height": 630,
                            "alt": "Cover",
                            "type": "image/png",
                        },
                    ],
                    "videos": ["/vid.mp4"],
                    "audio": ["/audio.mp3"],
                },
            },
            [
                '<meta property="og:title" content="OG Title" />',
                '<meta property="og:description" content="OG Description" />',
                '<meta property="og:url" content="https://example.com/post/1" />',
                '<meta property="og:site_name" content="Site" />',
                '<meta property="og:locale" content="en_US" />',
                '<meta property="og:type" content="article" />',
                '<meta property="og:determiner" content="the" />',
                '<meta property="og:country_name" content="USA" />',
                '<meta property="og:ttl" content="100" />',
                '<meta property="og:email" content="a@example.com" />',
                '<meta property="og:phone_number" content="+12025550199" />',
                '<meta property="og:fax_number" content="+12025550198" />',
                '<meta property="og:locale:alternate" content="fr_FR" />',
                '<meta property="og:image" content="https://example.com/img.png" />',
                '<meta property="og:image:secure_url" content="https://example.com/img-secure.png" />',
                '<meta property="og:image:width" content="1200" />',
                '<meta property="og:image:height" content="630" />',
                '<meta property="og:image:alt" content="Cover" />',
                '<meta property="og:image:type" content="image/png" />',
                '<meta property="og:video" content="https://example.com/vid.mp4" />',
                '<meta property="og:audio" content="https://example.com/audio.mp3" />',
            ],
            [],
            id="open-graph",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "twitter": {
                    "card": "summary_large_image",
                    "title": "TW Title",
                    "description": "TW Description",
                    "site": "@site",
                    "siteId": "site-id",
                    "creator": "@creator",
                    "creatorId": "creator-id",
                    "images": ["/a.png", {"url": "/b.png", "alt": "B image"}],
                },
            },
            [
                '<meta name="twitter:card" content="summary_large_image" />',
                '<meta name="twitter:title" content="TW Title" />',
                '<meta name="twitter:description" content="TW Description" />',
                '<meta name="twitter:site" content="@site" />',
                '<meta name="twitter:site:id" content="site-id" />',
                '<meta name="twitter:creator" content="@creator" />',
                '<meta name="twitter:creator:id" content="creator-id" />',
                '<meta name="twitter:image" content="https://example.com/a.png" />',
                '<meta name="twitter:image" content="https://example.com/b.png" />',
                '<meta name="twitter:image:alt" content="B image" />',
            ],
            [],
            id="twitter",
        ),
        pytest.param(
            {
                "verification": {
                    "google": ["google-token"],
                    "yahoo": ["yahoo-token"],
                    "yandex": ["yandex-token"],
                    "me": ["@me"],
                    "other": {"custom-token": ["a", "b"]},
                },
            },
            [
                '<meta name="google" content="google-token" />',
                '<meta name="yahoo" content="yahoo-token" />',
                '<meta name="yandex" content="yandex-token" />',
                '<meta name="me" content="@me" />',
                '<meta name="custom-token" content="a" />',
                '<meta name="custom-token" content="b" />',
            ],
            [],
            id="verification",
        ),
        pytest.param(
            {"appleWebApp": True},
            ['<meta name="apple-mobile-web-app-capable" content="yes" />'],
            [],
            id="apple-web-app-bool",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "appleWebApp": {
                    "capable": False,
                    "title": "App",
                    "statusBarStyle": "black-translucent",
                    "startupImage": [{"url": "/startup.png", "media": "(device-width: 768px)"}],
                },
            },
            [
                '<meta name="apple-mobile-web-app-capable" content="no" />',
                '<meta name="apple-mobile-web-app-title" content="App" />',
                '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />',
                (
                    '<link rel="apple-touch-startup-image" href="https://example.com/startup.png" '
                    'media="(device-width: 768px)" />'
                ),
            ],
            [],
            id="apple-web-app-object",
        ),
        pytest.param(
            {"formatDetection": {"telephone": False, "email": True, "address": False}},
            ['<meta name="format-detection" content="telephone=no, email=yes, address=no" />'],
            [],
            id="format-detection",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "itunes": {"appId": "123456", "appArgument": "/detail"},
            },
            ['<meta name="apple-itunes-app" content="app-id=123456, app-argument=https://example.com/detail" />'],
            [],
            id="itunes",
        ),
        pytest.param(
            {
                "facebook": {"appId": "fb-app", "admins": ["alice", "bob"]},
                "pinterest": {"richPin": True},
            },
            [
                '<meta property="fb:app_id" content="fb-app" />',
                '<meta property="fb:admins" content="alice" />',
                '<meta property="fb:admins" content="bob" />',
                '<meta name="pinterest-rich-pin" content="true" />',
            ],
            [],
            id="facebook-and-pinterest",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "manifest": "/manifest.webmanifest",
                "archives": ["/archive/2024"],
                "assets": ["/assets/main"],
                "bookmarks": ["/bookmarks/one"],
            },
            [
                '<link rel="manifest" href="https://example.com/manifest.webmanifest" />',
                '<link rel="archives" href="https://example.com/archive/2024" />',
                '<link rel="assets" href="https://example.com/assets/main" />',
                '<link rel="bookmark" href="https://example.com/bookmarks/one" />',
            ],
            [],
            id="manifest-archives-assets-bookmarks",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com",
                "appLinks": {
                    "ios": [{"url": "/ios", "appStoreId": "111", "appName": "App iOS"}],
                    "android": [
                        {
                            "url": "/android",
                            "package": "com.example.app",
                            "class": "com.example.Main",
                            "shouldFallback": False,
                        },
                    ],
                    "windowsUniversal": [{"url": "/uwp"}],
                },
            },
            [
                '<meta property="al:ios:url" content="https://example.com/ios" />',
                '<meta property="al:ios:app_store_id" content="111" />',
                '<meta property="al:ios:app_name" content="App iOS" />',
                '<meta property="al:android:url" content="https://example.com/android" />',
                '<meta property="al:android:package" content="com.example.app" />',
                '<meta property="al:android:class" content="com.example.Main" />',
                '<meta property="al:android:should_fallback" content="false" />',
                '<meta property="al:windows_universal:url" content="https://example.com/uwp" />',
            ],
            [],
            id="app-links",
        ),
        pytest.param(
            {"other": {"custom": "value", "bool-list": [True, False], "number": 3}},
            [
                '<meta name="custom" content="value" />',
                '<meta name="bool-list" content="true" />',
                '<meta name="bool-list" content="false" />',
                '<meta name="number" content="3" />',
            ],
            [],
            id="other",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com/base",
                "authors": [{"url": "/authors/ada"}],
                "manifest": "/manifest.webmanifest",
                "alternates": {"canonical": "/home"},
            },
            [
                '<link rel="author" href="https://example.com/authors/ada" />',
                '<link rel="manifest" href="https://example.com/manifest.webmanifest" />',
                '<link rel="canonical" href="https://example.com/home" />',
            ],
            [],
            id="relative-with-metadata-base",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com/base",
                "openGraph": {"url": "/post/1"},
                "twitter": {"images": ["/cover.png"]},
                "appLinks": {"ios": [{"url": "/ios"}]},
            },
            [
                '<meta property="og:url" content="https://example.com/post/1" />',
                '<meta name="twitter:image" content="https://example.com/cover.png" />',
                '<meta property="al:ios:url" content="https://example.com/ios" />',
            ],
            [],
            id="relative-og-twitter-app-links",
        ),
        pytest.param(
            {
                "metadataBase": "https://example.com/base",
                "openGraph": {"url": "https://cdn.example.net/post/1"},
                "icons": "https://cdn.example.net/favicon.ico",
            },
            [
                '<meta property="og:url" content="https://cdn.example.net/post/1" />',
                '<link rel="icon" href="https://cdn.example.net/favicon.ico" />',
            ],
            [],
            id="absolute-urls-not-rewritten",
        ),
        pytest.param(
            {
                "metadataBase": "/not-absolute",
                "manifest": "/manifest.webmanifest",
                "openGraph": {"url": "/post/1"},
            },
            [
                '<link rel="manifest" href="/manifest.webmanifest" />',
                '<meta property="og:url" content="/post/1" />',
            ],
            [],
            id="invalid-metadata-base-no-resolution",
        ),
    ],
)
def test_metadata_html_emission(metadata, expected_snippets, unexpected_snippets):
    html = unescape(ENV.render_template("metadata.html", metadata=metadata))

    for snippet in expected_snippets:
        assert snippet in html

    for snippet in unexpected_snippets:
        assert snippet not in html
