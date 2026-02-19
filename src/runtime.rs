use std::fmt;

use deno_core::{JsRuntime, RuntimeOptions, v8};

#[cfg(not(test))]
use pyo3::{
    IntoPyObjectExt,
    exceptions::{PyRuntimeError, PyTypeError},
    prelude::*,
    types::{PyDict, PyDictMethods, PyList, PyListMethods},
};

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
enum RuntimeErrorKind {
    Runtime,
    Type,
}

#[derive(Debug, Clone)]
struct RuntimeEvalError {
    kind: RuntimeErrorKind,
    message: String,
}

impl RuntimeEvalError {
    fn runtime(message: impl Into<String>) -> Self {
        Self {
            kind: RuntimeErrorKind::Runtime,
            message: message.into(),
        }
    }

    fn r#type(message: impl Into<String>) -> Self {
        Self {
            kind: RuntimeErrorKind::Type,
            message: message.into(),
        }
    }

    fn kind(&self) -> RuntimeErrorKind {
        self.kind
    }
}

impl fmt::Display for RuntimeEvalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}

struct RuntimeEngine {
    runtime: JsRuntime,
}

impl RuntimeEngine {
    fn new() -> Self {
        Self {
            runtime: JsRuntime::new(RuntimeOptions::default()),
        }
    }

    fn eval_json(&mut self, code: &str) -> Result<deno_core::serde_json::Value, RuntimeEvalError> {
        let global = self
            .runtime
            .execute_script("<anon>", code.to_owned())
            .map_err(|err| {
                RuntimeEvalError::runtime(format!("failed to execute javascript: {err:?}"))
            })?;

        deno_core::scope!(scope, self.runtime);
        let local = v8::Local::new(scope, global);
        if local.is_promise() {
            return Err(RuntimeEvalError::runtime(
                "javascript returned a Promise; Promise values are not supported",
            ));
        }
        if local.is_function() || local.is_symbol() || local.is_big_int() {
            return Err(RuntimeEvalError::r#type(
                "failed to convert JavaScript value to JSON-compatible output: unsupported JavaScript value type",
            ));
        }

        let converted = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            deno_core::serde_v8::from_v8::<deno_core::serde_json::Value>(scope, local)
        }))
        .map_err(|_| {
            RuntimeEvalError::r#type(
                "failed to convert JavaScript value to JSON-compatible output: unsupported JavaScript value type",
            )
        })?;

        converted.map_err(|err| {
            RuntimeEvalError::r#type(format!(
                "failed to convert JavaScript value to JSON-compatible output: {err:?}"
            ))
        })
    }
}

#[cfg(not(test))]
fn map_runtime_error(err: RuntimeEvalError) -> PyErr {
    match err.kind() {
        RuntimeErrorKind::Runtime => PyRuntimeError::new_err(err.to_string()),
        RuntimeErrorKind::Type => PyTypeError::new_err(err.to_string()),
    }
}

#[cfg(not(test))]
fn json_to_py(py: Python<'_>, value: deno_core::serde_json::Value) -> PyResult<Py<PyAny>> {
    match value {
        deno_core::serde_json::Value::Null => Ok(py.None()),
        deno_core::serde_json::Value::Bool(value) => value.into_py_any(py),
        deno_core::serde_json::Value::Number(number) => {
            if let Some(value) = number.as_i64() {
                return value.into_py_any(py);
            }
            if let Some(value) = number.as_u64() {
                return value.into_py_any(py);
            }
            if let Some(value) = number.as_f64() {
                return value.into_py_any(py);
            }
            Err(PyTypeError::new_err(format!(
                "unsupported JSON number value: {number}"
            )))
        }
        deno_core::serde_json::Value::String(value) => value.into_py_any(py),
        deno_core::serde_json::Value::Array(items) => {
            let list = PyList::empty(py);
            for item in items {
                list.append(json_to_py(py, item)?)?;
            }
            Ok(list.unbind().into_any())
        }
        deno_core::serde_json::Value::Object(entries) => {
            let dict = PyDict::new(py);
            for (key, value) in entries {
                dict.set_item(key, json_to_py(py, value)?)?;
            }
            Ok(dict.unbind().into_any())
        }
    }
}

#[cfg(not(test))]
#[pyclass(unsendable)]
pub(crate) struct Runtime {
    engine: RuntimeEngine,
}

#[cfg(not(test))]
#[pymethods]
impl Runtime {
    #[new]
    fn new() -> Self {
        Self {
            engine: RuntimeEngine::new(),
        }
    }

    fn __call__(&mut self, py: Python<'_>, code: &str) -> PyResult<Py<PyAny>> {
        let value = self.engine.eval_json(code).map_err(map_runtime_error)?;
        json_to_py(py, value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evaluates_arithmetic_expression() {
        let mut runtime = RuntimeEngine::new();
        let value = runtime
            .eval_json("let a = 1 + 4; a * 2")
            .expect("expected arithmetic expression to evaluate");
        assert_eq!(value, deno_core::serde_json::json!(10));
    }

    #[test]
    fn evaluates_objects_and_arrays() {
        let mut runtime = RuntimeEngine::new();
        let value = runtime
            .eval_json("({ok: true, values: [1, 2, 3], nested: {answer: 42}})")
            .expect("expected object expression to evaluate");
        assert_eq!(
            value,
            deno_core::serde_json::json!({
                "ok": true,
                "values": [1, 2, 3],
                "nested": {"answer": 42}
            })
        );
    }

    #[test]
    fn preserves_state_across_calls() {
        let mut runtime = RuntimeEngine::new();
        let first = runtime
            .eval_json("globalThis.counter = (globalThis.counter ?? 0) + 1; globalThis.counter")
            .expect("expected first counter update");
        let second = runtime
            .eval_json("globalThis.counter = (globalThis.counter ?? 0) + 1; globalThis.counter")
            .expect("expected second counter update");

        assert_eq!(first, deno_core::serde_json::json!(1));
        assert_eq!(second, deno_core::serde_json::json!(2));
    }

    #[test]
    fn surfaces_javascript_syntax_errors() {
        let mut runtime = RuntimeEngine::new();
        let err = runtime
            .eval_json("let a = ;")
            .expect_err("expected javascript syntax error");

        assert_eq!(err.kind(), RuntimeErrorKind::Runtime);
        assert!(err.to_string().contains("failed to execute javascript"));
    }

    #[test]
    fn rejects_promise_results() {
        let mut runtime = RuntimeEngine::new();
        let err = runtime
            .eval_json("Promise.resolve(1)")
            .expect_err("expected Promise to be rejected");

        assert_eq!(err.kind(), RuntimeErrorKind::Runtime);
        assert!(err.to_string().contains("Promise"));
    }

    #[test]
    fn rejects_unsupported_function_values() {
        let mut runtime = RuntimeEngine::new();
        let err = runtime
            .eval_json("(() => 1)")
            .expect_err("expected function value conversion to fail");

        assert_eq!(err.kind(), RuntimeErrorKind::Type);
        assert!(err.to_string().contains("JSON-compatible output"));
    }

    #[test]
    fn maps_null_and_undefined_to_null() {
        let mut runtime = RuntimeEngine::new();

        let null_value = runtime.eval_json("null").expect("expected null evaluation");
        let undefined_value = runtime
            .eval_json("undefined")
            .expect("expected undefined evaluation");

        assert_eq!(null_value, deno_core::serde_json::Value::Null);
        assert_eq!(undefined_value, deno_core::serde_json::Value::Null);
    }
}
