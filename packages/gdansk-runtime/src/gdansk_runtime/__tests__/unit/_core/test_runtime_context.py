from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from gdansk_runtime import Runtime, RuntimeContext, Script

if TYPE_CHECKING:
    from typing import assert_type

    _TYPING_CONTENTS = "export default function(input) { return input; }"

    _typing_script = Script(contents=_TYPING_CONTENTS, inputs=int, outputs=str)
    _typing_context: RuntimeContext[int, str] = Runtime()(_typing_script)
    assert_type(_typing_context, RuntimeContext[int, str])

    with _typing_context as _typing_run:
        assert_type(_typing_run, RuntimeContext[int, str])
        _typing_result: str = _typing_run(1)
        assert_type(_typing_result, str)


def test_runtime_executes_inline_script_with_pydantic_io():
    class Output(BaseModel):
        value: int
        kind: str

    script = Script(
        contents="""
export default function(input) {
    return { value: input, kind: typeof input };
}
""".strip(),
        inputs=int,
        outputs=Output,
    )

    with Runtime()(script) as run:
        result = run(cast("Any", "2"))

    assert result == Output(value=2, kind="number")


def test_runtime_supports_models_and_iterable_output():
    class ScriptInput(BaseModel):
        a: int
        b: tuple[int, int]

    class ScriptOutput(BaseModel):
        total: int

    script = Script(
        contents="""
export default function(input) {
    return [{ total: input.a + input.b[0] + input.b[1] }];
}
""".strip(),
        inputs=ScriptInput,
        outputs=Iterable[ScriptOutput],
    )

    with Runtime()(script) as run:
        result = list(run(cast("Any", {"a": "1", "b": ["2", "3"]})))

    assert result == [ScriptOutput(total=6)]


def test_output_validation_runs_after_javascript_execution():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    calls += 1;
    if (input) {
        return "bad";
    }
    return calls;
}
""".strip(),
        inputs=bool,
        outputs=int,
    )

    with Runtime()(script) as run:
        invalid_input = True
        with pytest.raises(ValidationError):
            run(invalid_input)

        valid_input = False
        assert run(valid_input) == 2


def test_runtime_context_shares_state_within_block():
    script = Script(
        contents="""
let counter = 0;

export default function(input) {
    counter += input;
    return counter;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 1
        assert run(2) == 3


def test_runtime_context_resets_state_across_blocks():
    script = Script(
        contents="""
let counter = 0;

export default function(input) {
    counter += input;
    return counter;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    runtime = Runtime()

    with runtime(script) as run:
        assert run(2) == 2

    with runtime(script) as run:
        assert run(2) == 2


def test_runtime_context_rejects_calls_before_enter():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)

    with pytest.raises(RuntimeError, match="not active"):
        context(1)


def test_runtime_context_rejects_reentry_while_active():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)

    with context, pytest.raises(RuntimeError, match="already active"):
        context.__enter__()


def test_runtime_context_can_be_reused_after_exit():
    script = Script(
        contents="""
let counter = 0;

export default function(input) {
    counter += input;
    return counter;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)

    with context:
        assert context(2) == 2

    with context:
        assert context(2) == 2


def test_runtime_context_rejects_calls_after_exit():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    run: RuntimeContext[int, int] | None = None

    with Runtime()(script) as handle:
        run = handle
        assert handle(1) == 2

    assert run is not None

    with pytest.raises(RuntimeError, match="not active"):
        run(1)


def test_runtime_context_can_be_reused_after_exception_exit():
    script = Script(
        contents="""
let counter = 0;

export default function(input) {
    counter += input;
    return counter;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)
    message = "boom"

    def run_and_raise() -> None:
        with context:
            assert context(2) == 2
            raise ValueError(message)

    with pytest.raises(ValueError, match=message):
        run_and_raise()

    with context:
        assert context(2) == 2


def test_runtime_rejects_missing_default_export():
    script = Script(
        contents="export const value = 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*missing"), Runtime()(script):
        pass


def test_runtime_rejects_non_function_default_export():
    script = Script(
        contents="export default 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*function"), Runtime()(script):
        pass


def test_runtime_surfaces_javascript_errors():
    script = Script(
        contents="""
export default function() {
    throw new Error("boom");
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run, pytest.raises(RuntimeError, match="boom"):
        run(1)


def test_runtime_rejects_unsupported_javascript_values():
    script = Script(
        contents="""
export default function() {
    return undefined;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run, pytest.raises(ValueError, match="unsupported JavaScript value"):
        run(1)


def test_runtime_does_not_run_javascript_when_input_validation_fails():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    calls += 1;
    return calls + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(ValidationError):
            run(cast("Any", "bad"))

        assert run(1) == 2


def test_runtime_does_not_run_javascript_when_input_cannot_serialize():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    calls += 1;
    return calls + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(TypeError, match="JSON-compatible"):
            run(10**100)

        assert run(1) == 2


def test_runtime_supports_async_default_export():
    script = Script(
        contents="""
export default async function(input) {
    return await Promise.resolve(input + 1);
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 2


def test_runtime_honors_top_level_await_before_calls():
    script = Script(
        contents="""
const offset = await Promise.resolve(41);

export default function(input) {
    return offset + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 42


def test_runtime_from_file_resolves_sibling_imports(tmp_path):
    (tmp_path / "other.js").write_text(
        "export function increment(value) { return value + 1; }\n",
        encoding="utf-8",
    )
    script_path = tmp_path / "script.js"
    script_path.write_text(
        """
import { increment } from "./other.js";

export default function(input) {
    return increment(input);
}
""".strip(),
        encoding="utf-8",
    )
    script = Script.from_file(script_path, inputs=int, outputs=int)

    with Runtime()(script) as run:
        assert run(1) == 2


def test_runtime_inline_script_resolves_relative_imports_from_package_json_directory(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "package.json").write_text(
        '{"name":"gdansk-runtime-test","private":true}\n',
        encoding="utf-8",
    )
    (project_dir / "other.js").write_text("export const offset = 41;\n", encoding="utf-8")
    script = Script(
        contents="""
import { offset } from "./other.js";

export default function(input) {
    return offset + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime(package_json=project_dir / "package.json")(script) as run:
        assert run(1) == 42


def test_runtime_exposes_web_api_globals():
    script = Script(
        contents="""
export default function() {
    const bytes = new TextEncoder().encode("hello");
    const text = new TextDecoder().decode(bytes);
    const location = new URL("/runtime?value=1", "https://example.com/base");
    const channel = new MessageChannel();
    const blob = new Blob(["hello"]);
    return {
        text,
        href: location.href,
        search: location.searchParams.get("value"),
        hasMessagePort:
            typeof channel.port1.postMessage === "function" &&
            typeof channel.port2.postMessage === "function",
        blobSize: blob.size,
        streamTypes: [
            typeof ReadableStream === "function",
            typeof WritableStream === "function",
            typeof TransformStream === "function",
        ],
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        result = run(0)

    assert result == {
        "text": "hello",
        "href": "https://example.com/runtime?value=1",
        "search": "1",
        "hasMessagePort": True,
        "blobSize": 5,
        "streamTypes": [True, True, True],
    }


def test_runtime_bootstraps_expanded_web_globals_before_module_evaluation():
    script = Script(
        contents="""
const bootstrapped =
    [
        typeof Event === "function",
        typeof EventTarget === "function",
        typeof BroadcastChannel === "function",
        typeof URLPattern === "function",
        typeof FileReader === "function",
        typeof CompressionStream === "function",
        typeof ImageData === "function",
        typeof ByteLengthQueuingStrategy === "function",
        typeof TextDecoderStream === "function",
        typeof PerformanceObserver === "function",
        typeof Window === "function",
        typeof Location === "function",
        typeof reportError === "function",
        typeof globalThis.addEventListener === "function",
        globalThis instanceof Window,
        location === undefined,
    ].every(Boolean);

export default function() {
    return bootstrapped;
}
""".strip(),
        inputs=int,
        outputs=bool,
    )

    with Runtime()(script) as run:
        assert run(0) is True


def test_runtime_supports_report_error_with_global_event_target():
    script = Script(
        contents="""
export default function() {
    let message = null;
    let targetMatches = false;

    globalThis.addEventListener("error", (event) => {
        message = event.message;
        targetMatches = event.target === globalThis;
        event.preventDefault();
    }, { once: true });

    reportError(new Error("boom"));

    return {
        message,
        targetMatches,
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        assert run(0) == {
            "message": "Uncaught Error: boom",
            "targetMatches": True,
        }


def test_runtime_supports_url_pattern():
    script = Script(
        contents="""
export default function() {
    const pattern = new URLPattern({
        pathname: "/posts/:id",
        search: "?draft=:draft",
    });
    const match = pattern.exec("https://example.com/posts/42?draft=yes");

    return {
        matched: match !== null,
        id: match?.pathname.groups.id ?? null,
        draft: match?.search.groups.draft ?? null,
        tested: pattern.test("https://example.com/posts/42?draft=yes"),
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        assert run(0) == {
            "matched": True,
            "id": "42",
            "draft": "yes",
            "tested": True,
        }


def test_runtime_supports_file_reader_binary_string():
    script = Script(
        contents="""
export default async function() {
    const reader = new FileReader();
    return await new Promise((resolve, reject) => {
        reader.addEventListener("load", () => {
            resolve({
                readyState: reader.readyState,
                result: reader.result,
            });
        }, { once: true });
        reader.addEventListener("error", () => {
            reject(reader.error ?? new Error("read failed"));
        }, { once: true });
        reader.readAsBinaryString(new Blob(["hello"]));
    });
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        assert run(0) == {
            "readyState": 2,
            "result": "hello",
        }


def test_runtime_supports_timers():
    script = Script(
        contents="""
export default async function(input) {
    return await new Promise((resolve) => {
        setTimeout(() => resolve(input + 1), 0);
    });
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 2


def test_runtime_uses_global_this_for_timer_callbacks_and_string_timers():
    script = Script(
        contents="""
export default async function() {
    const functionThis = await new Promise((resolve) => {
        setTimeout(function() {
            resolve(this === globalThis);
        }, 0);
    });

    globalThis.timerValue = 0;
    await new Promise((resolve) => {
        setTimeout("globalThis.timerValue = 42", 0);
        setTimeout(resolve, 0);
    });
    const timerValue = globalThis.timerValue;
    delete globalThis.timerValue;

    return {
        functionThis,
        timerValue,
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        assert run(0) == {
            "functionThis": True,
            "timerValue": 42,
        }


def test_runtime_set_timeout_honors_delay():
    script = Script(
        contents="""
export default async function() {
    const started = Date.now();
    await new Promise((resolve) => setTimeout(resolve, 50));
    return Date.now() - started;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(0) >= 40


def test_runtime_clear_timeout_prevents_callback():
    script = Script(
        contents="""
export default async function() {
    let called = false;
    const handle = setTimeout(() => {
        called = true;
    }, 20);
    clearTimeout(handle);
    await new Promise((resolve) => setTimeout(resolve, 40));
    return called;
}
""".strip(),
        inputs=int,
        outputs=bool,
    )

    with Runtime()(script) as run:
        assert run(0) is False


def test_runtime_set_interval_honors_delay_and_clear_interval_stops_repeats():
    script = Script(
        contents="""
export default async function() {
    const ticks = [];
    const started = Date.now();

    await new Promise((resolve) => {
        const handle = setInterval(() => {
            ticks.push(Date.now() - started);
            if (ticks.length === 3) {
                clearInterval(handle);
                resolve();
            }
        }, 20);
    });

    const beforeWait = ticks.length;
    await new Promise((resolve) => setTimeout(resolve, 40));
    return {
        ticks,
        beforeWait,
        afterWait: ticks.length,
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        result = run(0)

    ticks = cast("list[int]", result["ticks"])
    assert len(ticks) == 3
    assert ticks[0] >= 15
    assert ticks[1] >= ticks[0] + 15
    assert ticks[2] >= ticks[1] + 15
    assert result["beforeWait"] == 3
    assert result["afterWait"] == 3


def test_runtime_timeout_exceptions_report_error_without_aborting():
    script = Script(
        contents="""
export default async function() {
    const errors = [];

    globalThis.addEventListener("error", (event) => {
        errors.push(event.message);
        event.preventDefault();
    });

    setTimeout(() => {
        throw new Error("boom");
    }, 0);

    await new Promise((resolve) => setTimeout(resolve, 20));

    return {
        errors,
        completed: true,
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        assert run(0) == {
            "errors": ["Uncaught Error: boom"],
            "completed": True,
        }


def test_runtime_interval_exceptions_report_error_and_keep_running():
    script = Script(
        contents="""
export default async function() {
    const errors = [];
    let ticks = 0;

    globalThis.addEventListener("error", (event) => {
        errors.push(event.message);
        event.preventDefault();
    });

    await new Promise((resolve) => {
        const handle = setInterval(() => {
            ticks += 1;
            if (ticks === 1) {
                throw new Error("boom");
            }
            if (ticks === 3) {
                clearInterval(handle);
                resolve();
            }
        }, 0);
    });

    return {
        errors,
        ticks,
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        assert run(0) == {
            "errors": ["Uncaught Error: boom"],
            "ticks": 3,
        }


def test_runtime_recovers_after_javascript_error_within_context():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    if (input < 0) {
        throw new Error("boom");
    }
    calls += input;
    return calls;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(RuntimeError, match="boom"):
            run(-1)

        assert run(2) == 2


def test_runtime_recovers_after_deserialize_error_within_context():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    if (input < 0) {
        return undefined;
    }
    calls += input;
    return calls;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(ValueError, match="unsupported JavaScript value"):
            run(-1)

        assert run(2) == 2
