import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

_SNAKE_TO_CAMEL = re.compile(r"_([a-zA-Z0-9])")

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
        return {
            _SNAKE_TO_CAMEL.sub(lambda m: m.group(1).upper(), key): (
                renamed(item) if isinstance(item, Mapping) else item
            )
            for key, item in value.items()
        }

    def flatten(value: Meta, *, root: str) -> Meta:
        def fn(prefix: str, value: object) -> Meta:
            if not isinstance(value, Mapping):
                return {prefix: value}

            flattened = {}
            for key, item in value.items():
                flattened.update(fn(prefix=f"{prefix}/{key}", value=item))

            return flattened

        return fn(prefix=root, value=value)

    res = dict(renamed(value=meta))
    if openai := res.pop("openai", None):
        res.update(flatten(openai, root="openai"))

    return res
