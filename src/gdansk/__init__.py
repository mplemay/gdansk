from gdansk.core import Ship
from gdansk.vite import Vite
from gdansk.widget import FileParam, WidgetMeta

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__: tuple[str, ...] = (
    "FileParam",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "Ship",
    "Vite",
    "WidgetMeta",
)
