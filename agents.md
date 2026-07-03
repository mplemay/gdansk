# Agent Instructions

## Tooling

- **`uv`:** The python package manager.
  - *Usage:* `uv`
  - *Rules:*
    - **Always run `uv` with elevated permissions.**
    - **Don't use other package managers for python dependencies (ex: `pip`, `poetry`, etc.)**
- **`belgie`:** Frontend dependency execution for gdansk apps (configured by gdansk in `pyproject.toml`).
  - *Usage:* `uv run gdansk add`, `uv run gdansk lock`, `uv run gdansk update`, `uv run gdansk build`,
    `uv run gdansk dev`
  - *Rules:*
    - **Declare app/example frontend deps in `[gdansk.dependencies]` (and `[gdansk.dependencies.dev]`) tables in
      `pyproject.toml`.**
    - **Run `uv run gdansk lock` after manually changing gdansk dependency tables.**
    - **Prefer `uv run gdansk add <alias> <specifier>` when adding frontend dependencies.**
    - **Run frontend tasks via `uv run gdansk build` / `uv run gdansk dev`, not raw `vite` commands.**
    - **Don't use other package managers for javascript / typescript dependencies (ex: `bun`, `npm`, etc.)** in
      app/example roots.
    - **Don't add `package.json` or `deno.json` files to app/example frontend roots.**
    - **Keep `package.json` only for separately published JavaScript packages, such as `packages/widget` (which may use
      npm/deno in its own CI).**
    - **Commit `deno.lock` at the Python project root when gdansk dependencies change.**

## Conventions

- Error bindings: name caught exceptions `exc` in Python (`except SomeError as exc:`) and TypeScript/JavaScript
  (`catch (exc)`). Do not use `e`, `error`, `err`, `callError`, etc. For nested handlers that shadow an outer `exc`,
  use trailing underscores (`exc_`, `exc__`, …). Omit the binding when the value is unused (`except SomeError:` /
  `catch {`).

### Python

- The targets python versions greater than or equal to 3.11
- Given the project targets a more modern python, use functionality such as:
  - Modern type hints (`dict`)
  - Type parameters `class MyClass[T: MyParent]: ...`
  - The `Self` type for return types (`from typing import Self`)
- **Walrus operator (`:=`):** Prefer when a value is computed once and immediately tested, and the bound
  name is used in the `if` body or error message.
  - **Prefer when** merging assign + guard removes duplication or an extra line:
    - `.get()` + None / type guard: `if isinstance(table := gdansk.get("dependencies"), dict):`
    - `setdefault` + validation: `if not isinstance(gdansk := document.setdefault("gdansk", {}), dict):`
    - Property / path + guard: `if not (path := self.manifest_path).is_file():`
    - Avoid duplicate calls: `if isinstance(name, str) and (stripped := name.strip()):`
    - Dict lookup + reuse: `if (widget := manifest.widgets.get(key)) is None:`
  - **Do not use when:**
    - Assignment must happen before state is cleared (capture, mutate, then guard).
    - The name is needed throughout a function, not just in one guarded block.
    - Inside `assert` statements (RUF018; assignments are skipped under `python -O`).
    - The expression is trivial and a separate assign is clearer.
  - **Review checklist:** Is there an assign on the line above an `if` that only exists to feed that `if`?
    If yes, merge with `:=`.
- Type annotations:
  - **Do not** annotate `self` parameters - the type is implicit
  - Use `Self` for return types when returning the instance
  - Example: `def add_item(self, item: str) -> Self: ...` (note: no type on `self`)
- Classes and data structures:
  - Use `@dataclass` (from `dataclasses`) instead of manually defining `__init__` for data-holding classes
  - Consider using `slots=True` for memory efficiency and attribute access protection
  - Use `kw_only=True` to require keyword arguments for better readability at call sites
  - Use `frozen=True` for immutable data structures
  - Example: `@dataclass(slots=True, kw_only=True, frozen=True)`
  - **When NOT to use dataclass**:
    - Inheriting from non-dataclass parents (can cause MRO and initialization issues)
    - Need for `__new__` method (for singleton patterns, custom object creation)
    - Complex property logic with getters/setters that transform data
    - Need for `__init_subclass__` or metaclass customization
    - Classes with significant behavior/methods (prefer traditional classes for these)
  - **When to use dataclass**:
    - Simple data containers with minimal logic
    - Configuration objects, DTOs (Data Transfer Objects), result types
    - Immutable value objects (use `frozen=True`)
    - When you want automatic `__eq__`, `__repr__`, `__hash__` implementations
- Prefer importing using `from x import y` instead of `import x`
- Import local modules using the full path (ex: `from my_project.my_module import MyClass`)
- Internal compatibility module (`gdansk._core`) imports:
  - Prefer direct `from gdansk._core import ...` when there is no name clash in that file.
  - When a symbol from `_core` would clash with a Python-defined name in the same module, import with a `*Impl` /
    `*_impl` alias, then assign or wrap as needed:
    - Types/classes: `FooImpl` (e.g. `from gdansk._core import Foo as FooImpl`, then `Foo = FooImpl` or a thin wrapper).
    - Functions: `foo_impl` (snake_case with `_impl` suffix).
  - Do not use leading-underscore import aliases (`_Foo`, `_foo`) for this re-export pattern.
- **Don't use** docstrings, instead add inline comments only in places where there is complex or easily breakable logic
- **No file-wide suppressions** in source: do not use a first-line or module-wide pragma such as `# ruff: noqa: ...` for
  the whole file, a blanket `# type: ignore` on a module, or equivalent file-scoped pyright/bandit-style ignores.
- **Prefer fixing the cause**: adjust types or public API, or tooling configuration that matches documented conventions
  (for example `pyproject.toml`), so the diagnostic does not apply.
- **If suppression is unavoidable**, use the **smallest scope** (usually a single line) with **explicit rule codes**
  (for example `# noqa: ARG002`), not a whole-file waiver. This refers to pragmas in `.py` files, not to path-based
  rules in `pyproject.toml` (which should stay minimal and justified).
- For type aliases, prefer Python's modern syntax: `type MyAlias = SomeType` (PEP 695 style), especially in new code.
- Constants:
  - Module-level runtime constants must be public (no leading underscore), `SCREAMING_SNAKE_CASE`, and annotated with
    `Final[T]` from `typing`.
  - Example: `DEFAULT_HOST: Final[str] = "127.0.0.1"`
  - Does not apply to type aliases (`type Foo = ...`), TypedDict assignments, class instance attributes (including those
    annotated with `Final` in `__init__`), application wiring globals (`ship`, `mcp`, etc.), or special dunders
    (`__all__`, etc.).
- URL construction:
  - Use `urllib.parse` methods for URL manipulation (don't use string concatenation or f-strings for query params)
  - Use `urlencode()` for query parameters
  - Use `urlparse()` and `urlunparse()` for URL composition
  - Example: `urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(params), ""))`
  - This ensures proper encoding and avoids common URL injection vulnerabilities

### Testing

- Test files are named `test_<module>.py` to match the source module they test (e.g. tests for `core.py` go in
  `test_core.py`, tests for `_core` go in `test__core.py`)
- Do not name test files by functionality (e.g. avoid `test_ship_init.py`, `test_template.py`)
- Tests live under `__tests__/` with `unit/` and `integration/` subdirectories
- Integration tests are marked with `@pytest.mark.integration`

## Bundled agent skill

The `use-gdansk` skill at `src/gdansk/.agents/skills/use-gdansk/SKILL.md` documents the public integration surface
for external adoption. Point users and agents to `$use-gdansk` when they need to bootstrap or troubleshoot gdansk MCP
widget apps.

## Final Workflow

Run `uv run pytest` and `uv run prek run --all-files` with elevated permissions when needed. If you fix
anything, rerun those same commands until they pass, then `git commit` (with an all lowercase single-line conventional
commit message) and `git push`.
