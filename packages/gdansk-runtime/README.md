# Gdansk Runtime

## Specification

```python
from pydantic import BaseModel, TypeAdapter

class Script[I, O]:
    def __init__(
        self,
        contents: str,
        inputs: type[I],
        outputs: type[O],
    ) -> None: …
    @property
    def inputs(self) -> TypeAdapter[I]: …
    @property
    def outputs(self) -> TypeAdapter[O]: …
    @classmethod
    def from_file(
        cls: type[Self],
        path: str | PathLike[str],
        inputs: type[I],
        outputs: type[O],
    ) -> Self: …
    @property
    def contents(self) -> str: …

class Runtime:
    def __init__(self, *, package_json: str | PathLike[str] | None = None) -> None: …
    def lock(self) -> None: …
    async def alock(self) -> None: …
    def sync(self) -> None: …
    def __call__[I, O](self, script: Script[I, O], /) -> RuntimeContext[I, O]: …

class RuntimeContext[I, O]:
    def __enter__(self) -> RuntimeContext[I, O]: …
    async def __aenter__(self) -> AsyncRuntimeContext[I, O]: …
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: …
    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None: …
    def __call__(self, value: I, /) -> O: …

class AsyncRuntimeContext[I, O]:
    async def __call__(self, value: I, /) -> O: …

class MyScriptInput(BaseModel):
    a: int
    b: tuple[int, int]

class MyScriptOutput(BaseModel):
    pass

type MyScriptOutputs = Iterable[MyScriptOutput]

runtime = Runtime(package_json="package.json")
runtime.lock()
runtime.sync()

script = Script(contents="...", inputs=MyScriptInput, outputs=MyScriptOutputs)
input_adapter = script.inputs
output_adapter = script.outputs
with runtime(script) as run:
    out = run(…)

async with runtime(script) as run:
    out = await run(…)
````

`Script` wraps the provided `inputs` and `outputs` types in `TypeAdapter` instances and exposes
those adapters through the corresponding properties.

When `package_json` is configured, `Runtime.lock()` and `Runtime.alock()` write `deno.lock` next
to that `package.json`. `Runtime.sync()` resolves the same dependencies and installs them into a
`node_modules/` directory in that same folder. Locking and syncing are explicit operations in this
slice; entering a runtime context does not install dependencies.
