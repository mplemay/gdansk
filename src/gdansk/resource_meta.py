from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse, urlunparse


class WidgetCSP(TypedDict, total=False):
    connectDomains: list[str]
    resourceDomains: list[str]
    frameDomains: list[str]


class WidgetUI(TypedDict, total=False):
    csp: WidgetCSP
    domain: str


ResourceMeta = TypedDict(
    "ResourceMeta",
    {
        "openai/widgetDescription": str,
        "ui": WidgetUI,
    },
    total=False,
)

type ResourceMetaField = Literal[
    "base_url",
    "ui.domain",
    "ui.csp.connectDomains",
    "ui.csp.resourceDomains",
    "ui.csp.frameDomains",
]


@dataclass(slots=True, kw_only=True)
class MergedResourceMeta:
    connect_domains: list[str] = field(default_factory=list)
    domain: str | None = None
    frame_domains: list[str] = field(default_factory=list)
    resource_domains: list[str] = field(default_factory=list)
    widget_description: str | None = None


def merge_resource_meta(*metas: ResourceMeta | None) -> ResourceMeta | None:
    merged = MergedResourceMeta()

    for meta in metas:
        _merge_meta(merged, meta)

    return _build_resource_meta(merged)


def resource_meta_from_base_url(base_url: str | None) -> ResourceMeta | None:
    if base_url is None:
        return None

    origin = normalize_origin(base_url, field_name="base_url")
    return {
        "ui": {
            "csp": {
                "connectDomains": [origin],
                "resourceDomains": [origin],
            },
            "domain": origin,
        },
    }


def resource_meta_to_dict(meta: ResourceMeta | None) -> dict[str, Any] | None:
    if meta is None:
        return None

    result: dict[str, Any] = {}

    if (description := meta.get("openai/widgetDescription")) is not None:
        result["openai/widgetDescription"] = description

    if (ui_meta := _widget_ui_to_dict(meta.get("ui"))) is not None:
        result["ui"] = ui_meta

    return result or None


def merge_domains(
    existing: list[str],
    additional: list[str] | None,
    *,
    field_name: ResourceMetaField,
) -> list[str]:
    if additional is None:
        return list(existing)

    merged = list(existing)
    for domain in additional:
        normalized = normalize_origin(domain, field_name=field_name)
        if normalized not in merged:
            merged.append(normalized)

    return merged


def normalize_origin(value: str, *, field_name: ResourceMetaField) -> str:
    if not (parsed := urlparse(value)).scheme or parsed.hostname is None:
        msg = f"{field_name} must be an absolute URL with a hostname"
        raise ValueError(msg)

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, "", "", "", ""))


def _build_resource_meta(merged: MergedResourceMeta) -> ResourceMeta | None:
    result: ResourceMeta = {}
    if (ui := _build_widget_ui(merged)) is not None:
        result["ui"] = ui
    if merged.widget_description is not None:
        result["openai/widgetDescription"] = merged.widget_description
    return result or None


def _build_widget_csp(merged: MergedResourceMeta) -> WidgetCSP | None:
    csp: WidgetCSP = {}
    if merged.connect_domains:
        csp["connectDomains"] = merged.connect_domains
    if merged.resource_domains:
        csp["resourceDomains"] = merged.resource_domains
    if merged.frame_domains:
        csp["frameDomains"] = merged.frame_domains
    return csp or None


def _build_widget_ui(merged: MergedResourceMeta) -> WidgetUI | None:
    ui: WidgetUI = {}
    if (csp := _build_widget_csp(merged)) is not None:
        ui["csp"] = csp
    if merged.domain is not None:
        ui["domain"] = merged.domain
    return ui or None


def _merge_csp(merged: MergedResourceMeta, csp: WidgetCSP | None) -> None:
    if csp is None:
        return

    merged.connect_domains = merge_domains(
        merged.connect_domains,
        csp.get("connectDomains"),
        field_name="ui.csp.connectDomains",
    )
    merged.resource_domains = merge_domains(
        merged.resource_domains,
        csp.get("resourceDomains"),
        field_name="ui.csp.resourceDomains",
    )
    merged.frame_domains = merge_domains(
        merged.frame_domains,
        csp.get("frameDomains"),
        field_name="ui.csp.frameDomains",
    )


def _merge_meta(merged: MergedResourceMeta, meta: ResourceMeta | None) -> None:
    if meta is None:
        return

    if (description := meta.get("openai/widgetDescription")) is not None:
        merged.widget_description = description

    if (ui := meta.get("ui")) is None:
        return

    if (domain := ui.get("domain")) is not None:
        merged.domain = normalize_origin(domain, field_name="ui.domain")
    _merge_csp(merged, ui.get("csp"))


def _widget_csp_to_dict(csp: WidgetCSP | None) -> dict[str, Any] | None:
    if csp is None:
        return None

    result: dict[str, Any] = {}
    if (connect_domains := csp.get("connectDomains")) is not None:
        result["connectDomains"] = list(connect_domains)
    if (resource_domains := csp.get("resourceDomains")) is not None:
        result["resourceDomains"] = list(resource_domains)
    if (frame_domains := csp.get("frameDomains")) is not None:
        result["frameDomains"] = list(frame_domains)
    return result or None


def _widget_ui_to_dict(ui: WidgetUI | None) -> dict[str, Any] | None:
    if ui is None:
        return None

    result: dict[str, Any] = {}
    if (domain := ui.get("domain")) is not None:
        result["domain"] = domain
    if (csp := _widget_csp_to_dict(ui.get("csp"))) is not None:
        result["csp"] = csp
    return result or None
