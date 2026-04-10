from collections.abc import Sequence
from typing import Literal, TypedDict

type App = Literal["app"]
type Model = Literal["model"]


class WidgetCSPMeta(TypedDict, total=False):
    connect_domains: Sequence[str]
    resource_domains: Sequence[str]
    frame_domains: Sequence[str]


class WidgetUIMeta(TypedDict, total=False):
    prefers_border: bool
    visibility: tuple[App, Model] | tuple[Model, App] | tuple[App] | tuple[Model]
    domain: str
    resource_uri: str
    csp: WidgetCSPMeta


class OpenAIToolInvocationMeta(TypedDict, total=False):
    invoking: str
    invoked: str


class OpenAIWidgetMeta(TypedDict, total=False):
    resource_uri: str
    tool_invocation: OpenAIToolInvocationMeta
    file_params: Sequence[str]


class WidgetMeta(TypedDict, total=False):
    ui: WidgetUIMeta
    openai: OpenAIWidgetMeta
