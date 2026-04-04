# ruff: noqa: D100, D101, D102, D107, ARG002, ARG004

from __future__ import annotations

from os import PathLike, fspath
from pathlib import Path
from typing import Self, overload

from pydantic import TypeAdapter

from gdansk_runtime._core import Script as ScriptImpl

__all__ = ["Script"]


class Script[I, O](ScriptImpl):
    @overload
    def __new__(cls, contents: str, inputs: type[I], outputs: type[O]) -> Self: ...

    @overload
    def __new__(cls, contents: str, inputs: object, outputs: object) -> Self: ...

    def __new__(cls, contents: str, inputs: object, outputs: object) -> Self:
        if not contents.strip():
            msg = "Script.contents must not be empty"
            raise ValueError(msg)

        return super().__new__(cls, contents)

    @overload
    def __init__(self, contents: str, inputs: type[I], outputs: type[O]) -> None: ...

    @overload
    def __init__(self, contents: str, inputs: object, outputs: object) -> None: ...

    def __init__(self, contents: str, inputs: object, outputs: object) -> None:
        self._inputs: TypeAdapter[I] = TypeAdapter[I](inputs)
        self._outputs: TypeAdapter[O] = TypeAdapter[O](outputs)
        self._source_path: str | None = None

    @staticmethod
    def _normalize_source_path(path: str | PathLike[str]) -> str:
        normalized_path = fspath(path)
        if not isinstance(normalized_path, str):
            msg = "Script.from_file path must be a string path"
            raise TypeError(msg)

        return str(Path(normalized_path).resolve())

    @staticmethod
    def _read_contents_from_path(path: str | PathLike[str]) -> str:
        with Path(Script._normalize_source_path(path)).open("rb") as file:
            contents = file.read()

        try:
            return contents.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as err:
            msg = "Script file must contain valid UTF-8"
            raise OSError(msg) from err

    @classmethod
    @overload
    def from_file(
        cls: type[Self],
        path: str | PathLike[str],
        inputs: type[I],
        outputs: type[O],
    ) -> Self: ...

    @classmethod
    @overload
    def from_file(
        cls: type[Self],
        path: str | PathLike[str],
        inputs: object,
        outputs: object,
    ) -> Self: ...

    @classmethod
    def from_file(
        cls: type[Self],
        path: str | PathLike[str],
        inputs: object,
        outputs: object,
    ) -> Self:
        source_path = cls._normalize_source_path(path)
        script = cls(cls._read_contents_from_path(source_path), inputs, outputs)
        script._source_path = source_path
        return script

    def _serialize_input(self, value: I, /) -> object:
        validated = self._inputs.validate_python(value)
        return self._inputs.dump_python(validated, mode="json")

    def _deserialize_output(self, value: object, /) -> O:
        return self._outputs.validate_python(value)

    @property
    def inputs(self) -> TypeAdapter[I]:
        return self._inputs

    @property
    def outputs(self) -> TypeAdapter[O]:
        return self._outputs
