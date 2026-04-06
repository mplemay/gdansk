from os import PathLike
from typing import Self, overload

from pydantic import TypeAdapter

from gdansk_runtime._core import Script as ScriptImpl

class Script[I, O](ScriptImpl):
    @overload
    def __new__(cls, contents: str, inputs: type[I], outputs: type[O]) -> Self: ...
    @overload
    def __new__(cls, contents: str, inputs: object, outputs: object) -> Self: ...
    @overload
    def __init__(self, contents: str, inputs: type[I], outputs: type[O]) -> None: ...
    @overload
    def __init__(self, contents: str, inputs: object, outputs: object) -> None: ...
    @classmethod
    @overload
    def from_file[T, U](
        cls: type[Script[T, U]],
        path: str | PathLike[str],
        inputs: type[T],
        outputs: type[U],
    ) -> Script[T, U]: ...
    @classmethod
    @overload
    def from_file(
        cls: type[Self],
        path: str | PathLike[str],
        inputs: object,
        outputs: object,
    ) -> Self: ...
    @property
    def contents(self) -> str: ...
    @property
    def source_path(self) -> str | None: ...
    def serialize_input(self, value: I, /) -> object: ...
    def deserialize_output(self, value: object, /) -> O: ...
    @property
    def inputs(self) -> TypeAdapter[I]: ...
    @property
    def outputs(self) -> TypeAdapter[O]: ...
