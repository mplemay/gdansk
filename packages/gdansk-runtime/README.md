# Gdansk Runtime

## Specification

```python
from pydantic import BaseModel, TypeAdapter

class Script[I, O]:
    def __init__(
        self,
        contents: str,
        inputs: type[I] | TypeAdapter[I],
        outputs: type[O] | TypeAdapter[O],
    ) -> None: …
    @property
    def inputs(self) -> TypeAdapter[I]: …
    @property
    def outputs(self) -> TypeAdapter[O]: …
    @classmethod
    def from_file(
        cls: type[Self],
        path: str | PathLike[str],
        inputs: type[I] | TypeAdapter[I],
        outputs: type[O] | TypeAdapter[O],
    ) -> Self: …

type Deps = Mapper[str, str]

class Runtime:
    def __init__(self, *, dependencies: Deps | None = None) -> None: …
    def lock(self) -> None: …
    async def alock(self) -> None: …
    def sync(self) -> None: …
    async def async(self) -> None: …
    def __call__[I, O](self, script: Script[I, O], /) -> RuntimeContext[I, O]: …

class RuntimeContext[I, O]:
    def __enter__(self) -> RuntimeContext[I, O]: …
    async def __aenter__(self) -> AsyncRuntimeContext[I, O]: …
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: …
    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None: …
    def __call__(self, value: I, /) -> O: …

class AsyncRuntimeContext[I, O]:
    async def __call__(self, value: I, /) -> O: …

runtime = Runtime(…)
if not await runtime.locked():
    await runtime.alock()

if not await runtime.asynced():
    await runtime.async()

class MyScriptInput(BaseModel):
    a: int
    b: tuple[int, int]

class MyScriptOutput(BaseModel):
    pass

type MyScriptOutputs = Iterable[MyScriptOutput]

script = Script(contents="...", inputs=MyScriptInput, outputs=MyScriptOutputs)
input_adapter = script.inputs
output_adapter = script.outputs
with runtime(script) as run:
    out = run(…)

async with runtime(script) as run:
    out = await run(…)
````

`Script` normalizes `inputs` and `outputs` to `TypeAdapter` instances. If you want precise
static typing for special forms such as `Literal[...]` or `Annotated[...]`, pass an explicit
`TypeAdapter[...]` when constructing the script.
