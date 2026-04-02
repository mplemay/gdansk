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

    def __enter__(self, script: Script)  -> RuntimeContext: …
    async def __aenter__(self, script: Script) -> AsyncRuntimeContext: …

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
