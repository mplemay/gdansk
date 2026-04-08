# Agent Instructions

## Coding Guidelines

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is over complicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove preexisting dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multistep tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

## Tooling

### Package Management

- The package manger for the project is [uv](https://docs.astral.sh/uv/)
- Make `uv add` for core dependencies, `uv add --dev` for developer dependencies, and add optional features to groups
- It is also possible to remove packages using `uv remove`

## Conventions

### Python

- The targets python versions greater than or equal to 3.11
- Given the project targets a more modern python, use functionality such as:
  - The walrus operator (`:=`)
  - Modern type hints (`dict`)
  - Type parameters `class MyClass[T: MyParent]: ...`
  - The `Self` type for return types (`from typing import Self`)
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
- URL construction:
  - Use `urllib.parse` methods for URL manipulation (don't use string concatenation or f-strings for query params)
  - Use `urlencode()` for query parameters
  - Use `urlparse()` and `urlunparse()` for URL composition
  - Example: `urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(params), ""))`
  - This ensures proper encoding and avoids common URL injection vulnerabilities

### Testing

- Test files are named `test_<module>.py` to match the source module they test (e.g. tests for `core.py` go in
  `test_core.py`, tests for `_core` go in `test__core.py`)
- Do not name test files by functionality (e.g. avoid `test_amber_init.py`, `test_template.py`)
- Tests live under `__tests__/` with `unit/` and `integration/` subdirectories
- Integration tests are marked with `@pytest.mark.integration`

## Final Workflow

Run `cargo test`, `uv run pytest`, and `uv run prek run --all-files` with elevated permissions when needed.
If you fix anything, rerun those same commands until they pass, then `git commit` and `git push`.
