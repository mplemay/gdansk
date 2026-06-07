from gdansk._core import (
    GdanskError,
    GdanskJavaScriptError,
    GdanskModuleError,
    GdanskRuntimeError,
    PackageInstallResult,
    PackageUpdateChange,
    PackageUpdateResult,
    Runtime,
    RuntimeOptions,
    Script,
    ainstall_packages,
    alock_packages,
    aupdate_packages,
    install_packages,
    lock_packages,
    update_packages,
)
from gdansk.core import Ship as Ship
from gdansk.metadata import Metadata as Metadata
from gdansk.vite import Vite as Vite
from gdansk.widget import FileParam as FileParam, WidgetMeta as WidgetMeta

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__ = [
    "FileParam",
    "GdanskError",
    "GdanskJavaScriptError",
    "GdanskModuleError",
    "GdanskRuntimeError",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "Metadata",
    "PackageInstallResult",
    "PackageUpdateChange",
    "PackageUpdateResult",
    "Runtime",
    "RuntimeOptions",
    "Script",
    "Ship",
    "Vite",
    "WidgetMeta",
    "ainstall_packages",
    "alock_packages",
    "aupdate_packages",
    "install_packages",
    "lock_packages",
    "update_packages",
]
