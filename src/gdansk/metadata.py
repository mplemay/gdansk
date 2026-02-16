from __future__ import annotations

from typing import NotRequired, TypedDict, cast
from urllib.parse import urljoin, urlparse, urlunparse

Primitive = str | int | float | bool


class TitleTemplate(TypedDict, total=False):
    default: NotRequired[str]
    template: NotRequired[str]
    absolute: NotRequired[str]


class Author(TypedDict, total=False):
    name: NotRequired[str]
    url: NotRequired[str]


class ThemeColorDescriptor(TypedDict, total=False):
    color: str
    media: NotRequired[str]


class Viewport(TypedDict, total=False):
    width: NotRequired[str | int]
    height: NotRequired[str | int]
    initialScale: NotRequired[float]
    minimumScale: NotRequired[float]
    maximumScale: NotRequired[float]
    userScalable: NotRequired[bool]
    viewportFit: NotRequired[str]
    interactiveWidget: NotRequired[str]


class RobotsDirectives(TypedDict, total=False):
    index: NotRequired[bool]
    follow: NotRequired[bool]
    nocache: NotRequired[bool]
    noarchive: NotRequired[bool]
    nosnippet: NotRequired[bool]
    noimageindex: NotRequired[bool]
    maxVideoPreview: NotRequired[int]
    maxImagePreview: NotRequired[str]
    maxSnippet: NotRequired[int]
    unavailableAfter: NotRequired[str]


class Robots(RobotsDirectives, total=False):
    googleBot: NotRequired[str | RobotsDirectives]


class AlternateLinkDescriptor(TypedDict, total=False):
    url: str
    title: NotRequired[str]


class Alternates(TypedDict, total=False):
    canonical: NotRequired[str | AlternateLinkDescriptor]
    languages: NotRequired[dict[str, str | AlternateLinkDescriptor | list[str | AlternateLinkDescriptor]]]
    media: NotRequired[dict[str, str | AlternateLinkDescriptor | list[str | AlternateLinkDescriptor]]]
    types: NotRequired[dict[str, str | AlternateLinkDescriptor | list[str | AlternateLinkDescriptor]]]


class IconDescriptor(TypedDict, total=False):
    url: str
    rel: NotRequired[str]
    media: NotRequired[str]
    sizes: NotRequired[str]
    type: NotRequired[str]


class Icons(TypedDict, total=False):
    icon: NotRequired[str | IconDescriptor | list[str | IconDescriptor]]
    shortcut: NotRequired[str | IconDescriptor | list[str | IconDescriptor]]
    apple: NotRequired[str | IconDescriptor | list[str | IconDescriptor]]
    other: NotRequired[str | IconDescriptor | list[str | IconDescriptor]]


class OpenGraphMedia(TypedDict, total=False):
    url: str
    secureUrl: NotRequired[str]
    width: NotRequired[int]
    height: NotRequired[int]
    alt: NotRequired[str]
    type: NotRequired[str]


class OpenGraph(TypedDict, total=False):
    title: NotRequired[str]
    description: NotRequired[str]
    url: NotRequired[str]
    siteName: NotRequired[str]
    locale: NotRequired[str]
    type: NotRequired[str]
    determiner: NotRequired[str]
    countryName: NotRequired[str]
    ttl: NotRequired[int]
    emails: NotRequired[str | list[str]]
    phoneNumbers: NotRequired[str | list[str]]
    faxNumbers: NotRequired[str | list[str]]
    alternateLocale: NotRequired[str | list[str]]
    images: NotRequired[str | OpenGraphMedia | list[str | OpenGraphMedia]]
    videos: NotRequired[str | OpenGraphMedia | list[str | OpenGraphMedia]]
    audio: NotRequired[str | OpenGraphMedia | list[str | OpenGraphMedia]]


class TwitterImage(TypedDict, total=False):
    url: str
    alt: NotRequired[str]


class Twitter(TypedDict, total=False):
    card: NotRequired[str]
    title: NotRequired[str]
    description: NotRequired[str]
    site: NotRequired[str]
    siteId: NotRequired[str]
    creator: NotRequired[str]
    creatorId: NotRequired[str]
    images: NotRequired[str | TwitterImage | list[str | TwitterImage]]


class Verification(TypedDict, total=False):
    google: NotRequired[str | list[str]]
    yahoo: NotRequired[str | list[str]]
    yandex: NotRequired[str | list[str]]
    me: NotRequired[str | list[str]]
    other: NotRequired[dict[str, str | list[str]]]


class AppleWebAppStartupImage(TypedDict, total=False):
    url: str
    media: NotRequired[str]


class AppleWebApp(TypedDict, total=False):
    capable: NotRequired[bool]
    title: NotRequired[str]
    statusBarStyle: NotRequired[str]
    startupImage: NotRequired[str | AppleWebAppStartupImage | list[str | AppleWebAppStartupImage]]


class FormatDetection(TypedDict, total=False):
    telephone: NotRequired[bool]
    email: NotRequired[bool]
    address: NotRequired[bool]


class ITunes(TypedDict, total=False):
    appId: str
    appArgument: NotRequired[str]


class Facebook(TypedDict, total=False):
    appId: NotRequired[str]
    admins: NotRequired[str | list[str]]


class Pinterest(TypedDict, total=False):
    richPin: bool


AppLink = TypedDict(
    "AppLink",
    {
        "url": NotRequired[str],
        "appStoreId": NotRequired[str],
        "appName": NotRequired[str],
        "package": NotRequired[str],
        "class": NotRequired[str],
        "shouldFallback": NotRequired[bool],
    },
    total=False,
)


class AppLinks(TypedDict, total=False):
    ios: NotRequired[AppLink | list[AppLink]]
    iphone: NotRequired[AppLink | list[AppLink]]
    ipad: NotRequired[AppLink | list[AppLink]]
    android: NotRequired[AppLink | list[AppLink]]
    windows: NotRequired[AppLink | list[AppLink]]
    windowsUniversal: NotRequired[AppLink | list[AppLink]]
    web: NotRequired[AppLink | list[AppLink]]


class Metadata(TypedDict, total=False):
    metadataBase: NotRequired[str]
    title: NotRequired[str | TitleTemplate]
    description: NotRequired[str]
    applicationName: NotRequired[str]
    authors: NotRequired[Author | list[Author]]
    generator: NotRequired[str]
    keywords: NotRequired[str | list[str]]
    referrer: NotRequired[str]
    themeColor: NotRequired[str | ThemeColorDescriptor | list[str | ThemeColorDescriptor]]
    colorScheme: NotRequired[str]
    viewport: NotRequired[str | Viewport]
    creator: NotRequired[str]
    publisher: NotRequired[str]
    robots: NotRequired[str | Robots]
    alternates: NotRequired[Alternates]
    icons: NotRequired[str | IconDescriptor | list[str | IconDescriptor] | Icons]
    openGraph: NotRequired[OpenGraph]
    twitter: NotRequired[Twitter]
    verification: NotRequired[Verification]
    appleWebApp: NotRequired[bool | AppleWebApp]
    formatDetection: NotRequired[FormatDetection]
    itunes: NotRequired[ITunes]
    facebook: NotRequired[Facebook]
    pinterest: NotRequired[Pinterest]
    manifest: NotRequired[str]
    abstract: NotRequired[str]
    appLinks: NotRequired[AppLinks]
    archives: NotRequired[str | list[str]]
    assets: NotRequired[str | list[str]]
    bookmarks: NotRequired[str | list[str]]
    category: NotRequired[str]
    classification: NotRequired[str]
    other: NotRequired[dict[str, Primitive | list[Primitive]]]


def merge_metadata(base: Metadata | None, override: Metadata | None) -> Metadata | None:
    if base is None and override is None:
        return None

    if base is None:
        return cast("Metadata", {**cast("Metadata", override)})

    if override is None:
        return cast("Metadata", {**base})

    return cast("Metadata", {**base, **override})


def resolve_metadata_url(value: str, metadata_base: str | None) -> str:
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or metadata_base is None:
        return value

    base = urlparse(metadata_base)
    if not base.scheme or not base.netloc:
        return value

    base_path = base.path or "/"
    if not base_path.endswith("/"):
        base_path = f"{base_path}/"

    normalized_base = urlunparse((base.scheme, base.netloc, base_path, "", "", ""))
    return urljoin(normalized_base, value)
