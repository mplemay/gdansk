from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict, cast

type TransformedMeta = dict[str, object]

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


def _camelize(key: str) -> str:
    head, *tail = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _renamed_impl(value: object) -> object:
    if isinstance(value, Mapping):
        return {_camelize(str(key)): _renamed_impl(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed_impl(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_renamed_impl(item) for item in value)
    return value


def _flatten_impl(prefix: str, value: object) -> TransformedMeta:
    if isinstance(value, Mapping):
        flattened: TransformedMeta = {}
        for key, item in value.items():
            flattened.update(_flatten_impl(f"{prefix}/{key}", item))
        return flattened

    return {prefix: value}


def transform(meta: WidgetMeta | Mapping[str, object] | None) -> TransformedMeta:
    def renamed(value: object) -> object:
        return _renamed_impl(value)

    def flatten(prefix: str, value: object) -> TransformedMeta:
        return _flatten_impl(prefix, value)

    if meta is None:
        return {}

    renamed_meta = cast("TransformedMeta", renamed(dict(meta)))
    transformed: TransformedMeta = {}

    for key, value in renamed_meta.items():
        if key == "openai":
            transformed.update(flatten(key, value))
            continue

        transformed[key] = value

    return transformed
