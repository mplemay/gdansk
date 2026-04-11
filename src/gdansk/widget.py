from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

type Meta = Mapping[str, Any]

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
    widget_description: str
    tool_invocation: OpenAIToolInvocationMeta
    file_params: Sequence[str]


class WidgetMeta(TypedDict, total=False):
    ui: WidgetUIMeta
    openai: OpenAIWidgetMeta


def transform(meta: WidgetMeta) -> dict[str, Any]:
    def renamed(value: Meta) -> Meta:
        def fn(key: str) -> str:
            head, *tail = key.split("_")
            return head + "".join(part[:1].upper() + part[1:] for part in tail)

        return {fn(key): (renamed(item) if isinstance(Mapping, item) else item) for key, item in value.items()}

    def flatten(value: Meta) -> Meta:
        def fn(prefix: str, value: object) -> Meta:
            if not isinstance(value, Mapping):
                return {prefix: value}

            flattened = {}
            for key, item in value.items():
                flattened.update(fn(prefix=f"{prefix}/{key}", value=item))

            return flattened

        return fn(prefix="", value=value)

    res = dict(renamed(value=meta))
    if openai := res.pop("openai"):
        res.update(flatten(openai))

    return res
