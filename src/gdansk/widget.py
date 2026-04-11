import re
from collections.abc import Sequence
from typing import Final, Literal, TypedDict

type App = Literal["app"]
type Model = Literal["model"]
type Visibility = tuple[App, Model] | tuple[Model, App] | tuple[App] | tuple[Model]

SNAKE_TO_CAMEL: Final[re.Pattern[str]] = re.compile(r"_([a-zA-Z0-9])")


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
    csp: WidgetCSPMeta


ResourceMeta = TypedDict(
    "ResourceMeta",
    {
        "ui": ResourceUIMeta,
        "openai/widgetDescription": str,
    },
    total=False,
)


def transform(widget: WidgetMeta, extra: WidgetExtra) -> tuple[ToolMeta, ResourceMeta]:  # noqa: C901
    tool, resource = ToolMeta(), ResourceMeta()
    if ui := widget.get("ui", None):
        if (resource_uri := ui.get("resource_uri")) and (tm := tool.setdefault("ui", ToolUIMeta())):
            tm["resourceUri"] = resource_uri

        if (prefers_border := ui.get("prefers_border")) and (rm := resource.setdefault("ui", ResourceUIMeta())):
            rm["prefersBorder"] = prefers_border

        if (visibility := ui.get("visibility")) and (tm := tool.setdefault("ui", ToolUIMeta())):
            tm["visibility"] = visibility

    if openai := widget.get("openai", None):
        if tool_invocation := openai.get("tool_invocation"):
            if invoking := tool_invocation.get("invoking"):
                tool["openai/toolInvocation/invoking"] = invoking
            if invoked := tool_invocation.get("invoked"):
                tool["openai/toolInvocation/invoked"] = invoked

        if file_params := openai.get("file_params"):
            tool["openai/fileParams"] = file_params

        if widget_description := openai.get("widget_description"):
            resource["openai/widgetDescription"] = widget_description

    return tool, resource
