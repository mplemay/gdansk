from collections.abc import Sequence
from typing import Literal, TypedDict

type App = Literal["app"]
type Model = Literal["model"]
type Visibility = tuple[App, Model] | tuple[Model, App] | tuple[App] | tuple[Model]


class FileParam(TypedDict):
    download_url: str
    file_id: str


class WidgetExtra(TypedDict):
    uri: str
    base_url: str | None
    description: str | None


class WidgetCSPMeta(TypedDict, total=False):
    connect_domains: Sequence[str]
    resource_domains: Sequence[str]
    frame_domains: Sequence[str]


class WidgetUIMeta(TypedDict, total=False):
    resource_uri: str
    prefers_border: bool
    visibility: Visibility
    domain: str
    csp: WidgetCSPMeta


class OpenAIToolInvocationMeta(TypedDict, total=False):
    invoking: str
    invoked: str


class WidgetOpenAIMeta(TypedDict, total=False):
    widget_description: str
    tool_invocation: OpenAIToolInvocationMeta
    file_params: Sequence[str]


class WidgetMeta(TypedDict, total=False):
    ui: WidgetUIMeta
    openai: WidgetOpenAIMeta


class ToolUIMeta(TypedDict, total=False):
    visibility: Visibility
    resourceUri: str


ToolMeta = TypedDict(
    "ToolMeta",
    {
        "ui": ToolUIMeta,
        "openai/toolInvocation/invoking": str,
        "openai/toolInvocation/invoked": str,
        "openai/fileParams": Sequence[str],
    },
    total=False,
)


class ResourceCSPMeta(TypedDict, total=False):
    connectDomains: Sequence[str]
    resourceDomains: Sequence[str]
    frameDomains: Sequence[str]


class ResourceUIMeta(TypedDict, total=False):
    prefersBorder: bool
    domain: str
    csp: ResourceCSPMeta


ResourceMeta = TypedDict(
    "ResourceMeta",
    {
        "ui": ResourceUIMeta,
        "openai/widgetDescription": str,
    },
    total=False,
)


def _widget_csp_to_resource(csp: WidgetCSPMeta) -> ResourceCSPMeta | None:
    out: ResourceCSPMeta = {}
    if connect := csp.get("connect_domains"):
        out["connectDomains"] = connect
    if resource_domains := csp.get("resource_domains"):
        out["resourceDomains"] = resource_domains
    if frame_domains := csp.get("frame_domains"):
        out["frameDomains"] = frame_domains
    return out or None


def _apply_tool_ui(tool: ToolMeta, ui: WidgetUIMeta | None, extra: WidgetExtra) -> None:
    resource_uri = ui["resource_uri"] if ui and "resource_uri" in ui else extra["uri"]
    if resource_uri:
        tool.setdefault("ui", ToolUIMeta())["resourceUri"] = resource_uri
    if ui and "visibility" in ui and (visibility := ui.get("visibility")):
        tool.setdefault("ui", ToolUIMeta())["visibility"] = visibility


def _apply_resource_ui(resource: ResourceMeta, ui: WidgetUIMeta | None, extra: WidgetExtra) -> None:
    domain: str | None = ui["domain"] if ui and "domain" in ui else None
    if domain is None and extra.get("base_url"):
        domain = extra["base_url"]
    if domain:
        resource.setdefault("ui", ResourceUIMeta())["domain"] = domain
    if ui and "prefers_border" in ui:
        resource.setdefault("ui", ResourceUIMeta())["prefersBorder"] = ui["prefers_border"]
    if ui and (csp := ui.get("csp")) and (mapped := _widget_csp_to_resource(csp)):
        resource.setdefault("ui", ResourceUIMeta())["csp"] = mapped


def _apply_widget_description(
    resource: ResourceMeta,
    openai: WidgetOpenAIMeta | None,
    extra: WidgetExtra,
) -> None:
    widget_description = openai.get("widget_description") if openai and "widget_description" in openai else None
    if widget_description is not None:
        resource["openai/widgetDescription"] = widget_description
    elif desc := extra.get("description"):
        resource["openai/widgetDescription"] = desc


def _apply_openai_tool(tool: ToolMeta, openai: WidgetOpenAIMeta) -> None:
    if tool_invocation := openai.get("tool_invocation"):
        if invoking := tool_invocation.get("invoking"):
            tool["openai/toolInvocation/invoking"] = invoking
        if invoked := tool_invocation.get("invoked"):
            tool["openai/toolInvocation/invoked"] = invoked
    if file_params := openai.get("file_params"):
        tool["openai/fileParams"] = file_params


def transform(widget: WidgetMeta, extra: WidgetExtra) -> tuple[ToolMeta, ResourceMeta]:
    tool, resource = ToolMeta(), ResourceMeta()
    ui = widget.get("ui")
    openai = widget.get("openai")
    _apply_tool_ui(tool, ui, extra)
    _apply_resource_ui(resource, ui, extra)
    _apply_widget_description(resource, openai, extra)
    if openai:
        _apply_openai_tool(tool, openai)
    return tool, resource
