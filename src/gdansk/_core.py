from belgie._core import (
    RunTaskOptions,
    Runtime,
    RuntimeOptions,
    Script,
    TaskProcess,
    TaskRunner,
)
from belgie.dependencies import (
    PackageInstallResult,
    PackageUpdateChange,
    PackageUpdateResult,
    ainstall as ainstall_packages,
    alock as alock_packages,
    aupdate as aupdate_packages,
    install as install_packages,
    lock as lock_packages,
    update as update_packages,
)
from belgie.errors import (
    BelgieError as GdanskError,
    BelgieJavaScriptError as GdanskJavaScriptError,
    BelgieModuleError as GdanskModuleError,
    BelgieRuntimeError as GdanskRuntimeError,
)

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__: tuple[str, ...] = (
    "GdanskError",
    "GdanskJavaScriptError",
    "GdanskModuleError",
    "GdanskRuntimeError",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "PackageInstallResult",
    "PackageUpdateChange",
    "PackageUpdateResult",
    "RunTaskOptions",
    "Runtime",
    "RuntimeOptions",
    "Script",
    "TaskProcess",
    "TaskRunner",
    "ainstall_packages",
    "alock_packages",
    "aupdate_packages",
    "install_packages",
    "lock_packages",
    "update_packages",
)
