# Gdansk Runtime

## Specification

```python
class Script[I, O]:
    def __init__(self, contents: str, inputs: type[I], outputs: type[O]) -> None: …
    @classmethod
    def from_file(cls: type[Self], str | PathLike[str], inputs: type[I], outputs: type[O]) -> Self: …

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

type MyScriptInput(BaseModel):
  a: int
  b: tuple[int, int]

class MyScriptOutput(BaseModel):
  pass

type MyScriptOutputs = Iterable[MyScriptOutput]

script = Script(contents="...", inputs=MyScriptInput, outputs=MyScriptOutputs)
with runtime(script) as run:
    out = run(…)

async with runtime(script) as run:
    out = await run(…)
````
