use deno_core::{JsRuntime, RuntimeOptions, serde_json::Value, v8};

#[cfg(not(test))]
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
    types::{PyDict, PyList},
};

#[cfg_attr(test, allow(dead_code))]
#[derive(Debug)]
enum RuntimeError {
    Execution(String),
    Deserialize(String),
}

impl RuntimeError {
    fn execution(message: impl Into<String>) -> Self {
        Self::Execution(message.into())
    }

    fn deserialize(message: impl Into<String>) -> Self {
        Self::Deserialize(message.into())
    }
}

struct BasicRuntime {
    runtime: JsRuntime,
}

impl BasicRuntime {
    fn new() -> Self {
        Self {
            runtime: JsRuntime::new(RuntimeOptions::default()),
        }
    }

    fn eval_json_value(&mut self, code: &str) -> Result<Value, RuntimeError> {
        let code = code.to_owned();
        let output = self
            .runtime
            .execute_script("<gdansk-runtime>", code)
            .map_err(|err| RuntimeError::execution(format!("Execution error: {err:?}")))?;

        deno_core::scope!(scope, &mut self.runtime);
        let local = v8::Local::new(scope, output);
        if local.is_undefined()
            || local.is_function()
            || local.is_symbol()
            || local.is_big_int()
            || local.is_promise()
        {
            return Err(RuntimeError::deserialize(
                "Cannot deserialize value: unsupported JavaScript value".to_string(),
            ));
        }
        deno_core::serde_v8::from_v8::<Value>(scope, local)
            .map_err(|err| RuntimeError::deserialize(format!("Cannot deserialize value: {err:?}")))
    }
}

#[cfg(not(test))]
fn map_runtime_error(err: RuntimeError) -> PyErr {
    match err {
        RuntimeError::Execution(message) => PyRuntimeError::new_err(message),
        RuntimeError::Deserialize(message) => PyValueError::new_err(message),
    }
}

#[cfg(not(test))]
fn json_to_py(py: Python<'_>, value: &Value) -> PyResult<Py<PyAny>> {
    let py_value = match value {
        Value::Null => py.None(),
        Value::Bool(boolean) => (*boolean).into_pyobject(py)?.to_owned().into_any().unbind(),
        Value::Number(number) => {
            if let Some(number) = number.as_i64() {
                number.into_pyobject(py)?.into_any().unbind()
            } else if let Some(number) = number.as_u64() {
                number.into_pyobject(py)?.into_any().unbind()
            } else if let Some(number) = number.as_f64() {
                number.into_pyobject(py)?.into_any().unbind()
            } else {
                return Err(PyValueError::new_err(
                    "Cannot convert JSON number to Python object",
                ));
            }
        }
        Value::String(string) => string.into_pyobject(py)?.into_any().unbind(),
        Value::Array(items) => {
            let list = PyList::empty(py);
            for item in items {
                let item = json_to_py(py, item)?;
                list.append(item.bind(py))?;
            }
            list.into_any().unbind()
        }
        Value::Object(entries) => {
            let dict = PyDict::new(py);
            for (key, item) in entries {
                let item = json_to_py(py, item)?;
                dict.set_item(key, item.bind(py))?;
            }
            dict.into_any().unbind()
        }
    };
    Ok(py_value)
}

#[cfg(not(test))]
#[pyclass(unsendable)]
pub(crate) struct Runtime {
    inner: BasicRuntime,
}

#[cfg(not(test))]
#[pymethods]
impl Runtime {
    #[new]
    fn new() -> Self {
        Self {
            inner: BasicRuntime::new(),
        }
    }

    fn __call__(&mut self, py: Python<'_>, code: &str) -> PyResult<Py<PyAny>> {
        let value = self
            .inner
            .eval_json_value(code)
            .map_err(map_runtime_error)?;
        json_to_py(py, &value)
    }
}

#[cfg(test)]
mod tests {
    use deno_core::serde_json::json;

    use super::*;

    #[test]
    fn evaluates_basic_expression() {
        let mut runtime = BasicRuntime::new();
        let result = runtime
            .eval_json_value("let a = 1 + 4; a * 2")
            .expect("expected evaluation result");
        assert_eq!(result, json!(10));
    }

    #[test]
    fn preserves_state_across_calls() {
        let mut runtime = BasicRuntime::new();
        runtime
            .eval_json_value("globalThis.counter = 1")
            .expect("expected assignment to succeed");
        let result = runtime
            .eval_json_value("counter += 2; counter")
            .expect("expected stateful evaluation");
        assert_eq!(result, json!(3));
    }

    #[test]
    fn supports_nested_json_values() {
        let mut runtime = BasicRuntime::new();
        let result = runtime
            .eval_json_value(
                r#"({
  ok: true,
  count: 2,
  values: [1, { name: "gdansk" }, null]
})"#,
            )
            .expect("expected nested object result");
        assert_eq!(
            result,
            json!({
                "ok": true,
                "count": 2,
                "values": [1, {"name": "gdansk"}, null]
            })
        );
    }

    #[test]
    fn reports_syntax_errors_as_execution_errors() {
        let mut runtime = BasicRuntime::new();
        let result = runtime.eval_json_value("let = ;");
        let err = result.expect_err("expected syntax error");
        assert!(matches!(err, RuntimeError::Execution(_)));
    }

    #[test]
    fn reports_thrown_errors_as_execution_errors() {
        let mut runtime = BasicRuntime::new();
        let result = runtime.eval_json_value("throw new Error('boom')");
        let err = result.expect_err("expected thrown JS error");
        assert!(matches!(err, RuntimeError::Execution(_)));
    }

    #[test]
    fn rejects_undefined_results() {
        let mut runtime = BasicRuntime::new();
        let result = runtime.eval_json_value("undefined");
        let err = result.expect_err("expected deserialize error for undefined");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_function_results() {
        let mut runtime = BasicRuntime::new();
        let result = runtime.eval_json_value("(() => 42)");
        let err = result.expect_err("expected deserialize error for function value");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }
}
