from __future__ import annotations

# Component resource `_meta` for MCP Apps UI templates. Authoring uses nested `openai.*`
# keys; wire format uses slash keys (e.g. `openai/widgetDescription`). We omit
# `openai/outputTemplate` here — gdansk owns template URIs (`ui://...`).
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse, urlunparse


class WidgetCSP(TypedDict, total=False):
    connectDomains: list[str]
    resourceDomains: list[str]
    frameDomains: list[str]


class OpenAIWidgetCSP(TypedDict, total=False):
    connect_domains: list[str]
    resource_domains: list[str]
    frame_domains: list[str]
    redirect_domains: list[str]


class WidgetUI(TypedDict, total=False):
    prefersBorder: bool
    csp: WidgetCSP
    domain: str


class OpenAIWidgetResourceMeta(TypedDict, total=False):
    widgetDescription: str
    widgetPrefersBorder: bool
    widgetDomain: str
    widgetCSP: OpenAIWidgetCSP


class WidgetMeta(TypedDict, total=False):
    ui: WidgetUI
    openai: OpenAIWidgetResourceMeta


type WidgetMetaField = Literal[
    "base_url",
    "runtime_origin",
    "ui.domain",
    "ui.csp.connectDomains",
    "ui.csp.resourceDomains",
    "ui.csp.frameDomains",
    "openai.widgetCSP.connect_domains",
    "openai.widgetCSP.resource_domains",
    "openai.widgetCSP.frame_domains",
    "openai.widgetCSP.redirect_domains",
    "openai.widgetDomain",
]


@dataclass(slots=True, kw_only=True)
class MergedWidgetMeta:
    connect_domains: list[str] = field(default_factory=list)
    domain: str | None = None
    frame_domains: list[str] = field(default_factory=list)
    prefers_border: bool | None = None
    redirect_domains: list[str] = field(default_factory=list)
    resource_domains: list[str] = field(default_factory=list)
    widget_description: str | None = None


def merge_widget_meta(*metas: WidgetMeta | None) -> WidgetMeta | None:
    merged = MergedWidgetMeta()

    for meta in metas:
        _merge_meta(merged, meta)

    return _build_widget_meta(merged)


def widget_meta_from_base_url(base_url: str | None) -> WidgetMeta | None:
    if base_url is None:
        return None

    origin = normalize_origin(base_url, field_name="base_url")
    return {
        "ui": {
            **_widget_meta_csp_from_origin(origin, field_name="base_url")["ui"],
            "domain": origin,
        },
    }


def widget_meta_to_dict(meta: WidgetMeta | None) -> dict[str, Any] | None:
    if meta is None:
        return None

    result: dict[str, Any] = {}

    if (openai := meta.get("openai")) is not None:
        if (description := openai.get("widgetDescription")) is not None:
            result["openai/widgetDescription"] = description
        if (prefers := openai.get("widgetPrefersBorder")) is not None:
            result["openai/widgetPrefersBorder"] = prefers
        if (domain := openai.get("widgetDomain")) is not None:
            result["openai/widgetDomain"] = domain
        if (csp := _openai_widget_csp_to_dict(openai.get("widgetCSP"))) is not None:
            result["openai/widgetCSP"] = csp

    if (ui_meta := _widget_ui_to_dict(meta.get("ui"))) is not None:
        result["ui"] = ui_meta

    return result or None


def merge_domains(
    existing: list[str],
    additional: list[str] | None,
    *,
    field_name: WidgetMetaField,
) -> list[str]:
    if additional is None:
        return list(existing)

    merged = list(existing)
    for domain in additional:
        normalized = normalize_origin(domain, field_name=field_name)
        if normalized not in merged:
            merged.append(normalized)

    return merged


def normalize_origin(value: str, *, field_name: WidgetMetaField) -> str:
    if not (parsed := urlparse(value)).scheme or parsed.hostname is None:
        msg = f"{field_name} must be an absolute URL with a hostname"
        raise ValueError(msg)

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, "", "", "", ""))


def _widget_meta_csp_from_origin(origin: str, *, field_name: WidgetMetaField) -> WidgetMeta:
    normalized_origin = normalize_origin(origin, field_name=field_name)
    return {
        "ui": {
            "csp": {
                "connectDomains": [normalized_origin],
                "resourceDomains": [normalized_origin],
            },
        },
    }


def _build_widget_meta(merged: MergedWidgetMeta) -> WidgetMeta | None:
    result: WidgetMeta = {}
    if (ui := _build_widget_ui(merged)) is not None:
        result["ui"] = ui
    if (openai := _build_openai_resource_meta(merged)) is not None:
        result["openai"] = openai
    return result or None


def _build_openai_resource_meta(merged: MergedWidgetMeta) -> OpenAIWidgetResourceMeta | None:
    openai: OpenAIWidgetResourceMeta = {}
    if merged.widget_description is not None:
        openai["widgetDescription"] = merged.widget_description
    if merged.redirect_domains:
        openai["widgetCSP"] = {"redirect_domains": list(merged.redirect_domains)}
    return openai or None


def _build_widget_csp(merged: MergedWidgetMeta) -> WidgetCSP | None:
    csp: WidgetCSP = {}
    if merged.connect_domains:
        csp["connectDomains"] = merged.connect_domains
    if merged.resource_domains:
        csp["resourceDomains"] = merged.resource_domains
    if merged.frame_domains:
        csp["frameDomains"] = merged.frame_domains
    return csp or None


def _build_widget_ui(merged: MergedWidgetMeta) -> WidgetUI | None:
    ui: WidgetUI = {}
    if merged.prefers_border is not None:
        ui["prefersBorder"] = merged.prefers_border
    if (csp := _build_widget_csp(merged)) is not None:
        ui["csp"] = csp
    if merged.domain is not None:
        ui["domain"] = merged.domain
    return ui or None


def _merge_openai_widget_csp(merged: MergedWidgetMeta, csp: OpenAIWidgetCSP | None) -> None:
    if csp is None:
        return

    merged.connect_domains = merge_domains(
        merged.connect_domains,
        csp.get("connect_domains"),
        field_name="openai.widgetCSP.connect_domains",
    )
    merged.resource_domains = merge_domains(
        merged.resource_domains,
        csp.get("resource_domains"),
        field_name="openai.widgetCSP.resource_domains",
    )
    merged.frame_domains = merge_domains(
        merged.frame_domains,
        csp.get("frame_domains"),
        field_name="openai.widgetCSP.frame_domains",
    )
    merged.redirect_domains = merge_domains(
        merged.redirect_domains,
        csp.get("redirect_domains"),
        field_name="openai.widgetCSP.redirect_domains",
    )


def _merge_csp(merged: MergedWidgetMeta, csp: WidgetCSP | None) -> None:
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


def _merge_meta(merged: MergedWidgetMeta, meta: WidgetMeta | None) -> None:
    if meta is None:
        return

    if (ui := meta.get("ui")) is not None:
        if (domain := ui.get("domain")) is not None:
            merged.domain = normalize_origin(domain, field_name="ui.domain")
        if (prefers := ui.get("prefersBorder")) is not None:
            merged.prefers_border = prefers
        _merge_csp(merged, ui.get("csp"))

    if (openai := meta.get("openai")) is not None:
        if (description := openai.get("widgetDescription")) is not None:
            merged.widget_description = description
        if (prefers := openai.get("widgetPrefersBorder")) is not None:
            merged.prefers_border = prefers
        if (domain := openai.get("widgetDomain")) is not None:
            merged.domain = normalize_origin(domain, field_name="openai.widgetDomain")
        _merge_openai_widget_csp(merged, openai.get("widgetCSP"))


def _openai_widget_csp_to_dict(csp: OpenAIWidgetCSP | None) -> dict[str, Any] | None:
    if csp is None:
        return None

    result: dict[str, Any] = {}
    if (connect := csp.get("connect_domains")) is not None:
        result["connect_domains"] = list(connect)
    if (resource := csp.get("resource_domains")) is not None:
        result["resource_domains"] = list(resource)
    if (frame := csp.get("frame_domains")) is not None:
        result["frame_domains"] = list(frame)
    if (redirect := csp.get("redirect_domains")) is not None:
        result["redirect_domains"] = list(redirect)
    return result or None


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
    if (prefers := ui.get("prefersBorder")) is not None:
        result["prefersBorder"] = prefers
    if (domain := ui.get("domain")) is not None:
        result["domain"] = domain
    if (csp := _widget_csp_to_dict(ui.get("csp"))) is not None:
        result["csp"] = csp
    return result or None
