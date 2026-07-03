from gdansk.core import Ship as Ship
from gdansk.vite import Vite as Vite
from gdansk.widget import FileParam as FileParam, WidgetMeta as WidgetMeta

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__ = [
    "FileParam",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "Ship",
    "Vite",
    "WidgetMeta",
]
