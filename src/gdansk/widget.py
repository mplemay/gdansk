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


def _transform_resource_csp(widget: WidgetMeta, _: WidgetExtra) -> ResourceCSPMeta | None:
    ui = widget.get("ui")
    if not ui or (csp := ui.get("csp")) is None:
        return None
    out: ResourceCSPMeta = {}
    if connect := csp.get("connect_domains"):
        out["connectDomains"] = connect
    if resource_domains := csp.get("resource_domains"):
        out["resourceDomains"] = resource_domains
    if frame_domains := csp.get("frame_domains"):
        out["frameDomains"] = frame_domains
    return out or None


def _transform_resource_ui(widget: WidgetMeta, extra: WidgetExtra) -> ResourceUIMeta | None:
    ui = widget.get("ui")
    out: ResourceUIMeta = {}
    domain: str | None = ui["domain"] if ui and "domain" in ui else None
    if domain is None and extra.get("base_url"):
        domain = extra["base_url"]
    if domain:
        out["domain"] = domain
    if ui and "prefers_border" in ui:
        out["prefersBorder"] = ui["prefers_border"]
    if csp := _transform_resource_csp(widget, extra):
        out["csp"] = csp
    return out or None


def _transform_resource(widget: WidgetMeta, extra: WidgetExtra) -> ResourceMeta:
    out: ResourceMeta = {}
    if ui := _transform_resource_ui(widget, extra):
        out["ui"] = ui
    openai = widget.get("openai")
    widget_description: str | None = None
    if openai and "widget_description" in openai:
        wd = openai["widget_description"]
        if wd is not None:
            widget_description = wd
    if widget_description is None and (desc := extra.get("description")):
        widget_description = desc
    if widget_description is not None:
        out["openai/widgetDescription"] = widget_description
    return out


def _transform_tool_ui(widget: WidgetMeta, extra: WidgetExtra) -> ToolUIMeta | None:
    ui = widget.get("ui")
    out: ToolUIMeta = {}
    resource_uri = ui["resource_uri"] if ui and "resource_uri" in ui else extra["uri"]
    if resource_uri:
        out["resourceUri"] = resource_uri
    if ui and "visibility" in ui and (visibility := ui.get("visibility")):
        out["visibility"] = visibility
    return out or None


def _transform_tool(widget: WidgetMeta, extra: WidgetExtra) -> ToolMeta:
    out: ToolMeta = {}
    if ui := _transform_tool_ui(widget, extra):
        out["ui"] = ui
    if openai := widget.get("openai"):
        if tool_invocation := openai.get("tool_invocation"):
            if invoking := tool_invocation.get("invoking"):
                out["openai/toolInvocation/invoking"] = invoking
            if invoked := tool_invocation.get("invoked"):
                out["openai/toolInvocation/invoked"] = invoked
        if file_params := openai.get("file_params"):
            out["openai/fileParams"] = file_params
    return out


def transform(widget: WidgetMeta, extra: WidgetExtra) -> tuple[ToolMeta, ResourceMeta]:
    return _transform_tool(widget, extra), _transform_resource(widget, extra)
