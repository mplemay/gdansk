use deno_core::{
    JsRuntime, OpState, PollEventLoopOptions, RuntimeOptions, op2, serde_json::Value, v8,
};

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

#[derive(Default)]
struct SsrCapture {
    html: Option<String>,
}

#[op2(fast)]
fn op_gdansk_set_html(state: &mut OpState, #[string] html: String) {
    state.borrow_mut::<SsrCapture>().html = Some(html);
}

deno_core::extension!(
    gdansk_runtime_ext,
    ops = [op_gdansk_set_html],
    state = |state| state.put(SsrCapture::default())
);

fn execution_error(err: impl std::fmt::Debug) -> RuntimeError {
    RuntimeError::execution(format!("Execution error: {err:?}"))
}

fn snapshot() -> &'static [u8] {
    include_bytes!(concat!(env!("OUT_DIR"), "/GDANSK_RUNTIME_SNAPSHOT.bin"))
}

fn read_json_value(
    runtime: &mut JsRuntime,
    output: v8::Global<v8::Value>,
) -> Result<Value, RuntimeError> {
    deno_core::scope!(scope, runtime);
    let local = v8::Local::new(scope, output);
    if local.is_number() {
        let Some(number) = local.number_value(scope) else {
            return Err(RuntimeError::deserialize(
                "Cannot deserialize value: unsupported JavaScript value",
            ));
        };
        if !number.is_finite() {
            return Err(RuntimeError::deserialize(
                "Cannot deserialize value: unsupported JavaScript value",
            ));
        }
    }
    if local.is_undefined()
        || local.is_function()
        || local.is_symbol()
        || local.is_big_int()
        || local.is_promise()
    {
        return Err(RuntimeError::deserialize(
            "Cannot deserialize value: unsupported JavaScript value",
        ));
    }
    deno_core::serde_v8::from_v8::<Value>(scope, local)
        .map_err(|err| RuntimeError::deserialize(format!("Cannot deserialize value: {err:?}")))
}

async fn evaluate(code: &str) -> Result<Value, RuntimeError> {
    let mut runtime = JsRuntime::new(RuntimeOptions {
        startup_snapshot: Some(snapshot()),
        extensions: vec![gdansk_runtime_ext::init()],
        ..Default::default()
    });

    {
        let op_state = runtime.op_state();
        let mut op_state = op_state.borrow_mut();
        op_state.borrow_mut::<SsrCapture>().html = None;
    }

    let module_specifier =
        deno_core::resolve_url("file:///gdansk/runtime_eval.js").map_err(execution_error)?;
    let code_json = deno_core::serde_json::to_string(code).map_err(execution_error)?;
    let module_code = format!(
        "import {{ runCode }} from \"gdansk:runtime\";\nglobalThis.__gdansk_last_result = runCode({code_json});"
    );

    let mod_id = runtime
        .load_main_es_module_from_code(&module_specifier, module_code)
        .await
        .map_err(execution_error)?;

    let result = runtime.mod_evaluate(mod_id);
    runtime
        .run_event_loop(PollEventLoopOptions::default())
        .await
        .map_err(execution_error)?;
    result.await.map_err(execution_error)?;

    let html = {
        let op_state = runtime.op_state();
        let mut op_state = op_state.borrow_mut();
        op_state.borrow_mut::<SsrCapture>().html.take()
    };

    if let Some(html) = html {
        return Ok(Value::String(html));
    }

    let output = runtime
        .execute_script("<gdansk-runtime-result>", "globalThis.__gdansk_last_result")
        .map_err(execution_error)?;

    read_json_value(&mut runtime, output)
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
#[pyfunction]
pub(crate) fn run<'py>(py: Python<'py>, code: &str) -> PyResult<Bound<'py, PyAny>> {
    let code = code.to_owned();
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let value = tokio::task::spawn_blocking(move || -> PyResult<Value> {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(execution_error)
                .map_err(map_runtime_error)?;
            runtime.block_on(evaluate(&code)).map_err(map_runtime_error)
        })
        .await
        .map_err(|err| map_runtime_error(execution_error(err)))??;
        Python::attach(|py| json_to_py(py, &value))
    })
}

#[cfg(test)]
mod tests {
    use deno_core::serde_json::json;

    use super::*;

    fn run_value(code: &str) -> Result<Value, RuntimeError> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(execution_error)?;
        runtime.block_on(evaluate(code))
    }

    #[test]
    fn evaluates_basic_expression() {
        let result = run_value("let a = 1 + 4; a * 2").expect("expected evaluation result");
        assert_eq!(result, json!(10));
    }

    #[test]
    fn does_not_preserve_state_across_calls() {
        run_value("globalThis.counter = 1").expect("expected assignment to succeed");
        let result = run_value("counter += 2; counter");
        let err = result.expect_err("expected stateless evaluation");
        assert!(matches!(err, RuntimeError::Execution(_)));
    }

    #[test]
    fn supports_nested_json_values() {
        let result = run_value(
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
        let result = run_value("let = ;");
        let err = result.expect_err("expected syntax error");
        assert!(matches!(err, RuntimeError::Execution(_)));
    }

    #[test]
    fn reports_thrown_errors_as_execution_errors() {
        let result = run_value("throw new Error('boom')");
        let err = result.expect_err("expected thrown JS error");
        assert!(matches!(err, RuntimeError::Execution(_)));
    }

    #[test]
    fn rejects_undefined_results() {
        let result = run_value("undefined");
        let err = result.expect_err("expected deserialize error for undefined");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_function_results() {
        let result = run_value("(() => 42)");
        let err = result.expect_err("expected deserialize error for function value");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_symbol_results() {
        let result = run_value("Symbol('x')");
        let err = result.expect_err("expected deserialize error for symbol value");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_bigint_results() {
        let result = run_value("1n");
        let err = result.expect_err("expected deserialize error for bigint value");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_promise_results() {
        let result = run_value("Promise.resolve(1)");
        let err = result.expect_err("expected deserialize error for promise value");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_nan_results() {
        let result = run_value("0/0");
        let err = result.expect_err("expected deserialize error for NaN");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_positive_infinity_results() {
        let result = run_value("1/0");
        let err = result.expect_err("expected deserialize error for Infinity");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn rejects_negative_infinity_results() {
        let result = run_value("-1/0");
        let err = result.expect_err("expected deserialize error for -Infinity");
        assert!(matches!(err, RuntimeError::Deserialize(_)));
    }

    #[test]
    fn execution_error_does_not_poison_runtime() {
        let result = run_value("throw new Error('boom')");
        let err = result.expect_err("expected execution error");
        assert!(matches!(err, RuntimeError::Execution(_)));

        let recovered =
            run_value("40 + 2").expect("expected runtime to recover after execution error");
        assert_eq!(recovered, json!(42));
    }

    #[test]
    fn deserialize_error_does_not_poison_runtime() {
        let result = run_value("Symbol('x')");
        let err = result.expect_err("expected deserialize error");
        assert!(matches!(err, RuntimeError::Deserialize(_)));

        let recovered =
            run_value("50 + 2").expect("expected runtime to recover after deserialize error");
        assert_eq!(recovered, json!(52));
    }

    #[test]
    fn supports_empty_object_and_array() {
        let object = run_value("({})").expect("expected empty object to deserialize");
        assert_eq!(object, json!({}));

        let array = run_value("[]").expect("expected empty array to deserialize");
        assert_eq!(array, json!([]));
    }

    #[test]
    fn supports_unicode_string_values() {
        let result = run_value(r#""café 👋""#).expect("expected unicode string to deserialize");
        assert_eq!(result, json!("café 👋"));
    }

    #[test]
    fn evaluates_html_from_op_capture() {
        let result = run_value(r#"Deno.core.ops.op_gdansk_set_html("<div>ok</div>");"#)
            .expect("expected SSR output");
        assert_eq!(result, json!("<div>ok</div>"));
    }

    #[test]
    fn returns_eval_result_when_ssr_output_is_not_set() {
        let result = run_value("1 + 1").expect("expected evaluation result");
        assert_eq!(result, json!(2));
    }

    #[test]
    fn ssr_capture_takes_precedence_over_eval_result() {
        let result = run_value(r#"Deno.core.ops.op_gdansk_set_html("<div>ok</div>"); 1 + 1"#)
            .expect("expected SSR output");
        assert_eq!(result, json!("<div>ok</div>"));
    }

    #[test]
    fn reports_ssr_execution_failures_as_execution_errors() {
        let result = run_value("throw new Error('ssr boom')");
        let err = result.expect_err("expected SSR execution error");
        assert!(matches!(err, RuntimeError::Execution(_)));
    }

    #[test]
    fn ssr_output_does_not_leak_between_calls() {
        let first = run_value(r#"Deno.core.ops.op_gdansk_set_html("<div>ok</div>");"#)
            .expect("expected first SSR output");
        assert_eq!(first, json!("<div>ok</div>"));

        let second = run_value("2 + 2").expect("expected regular eval output");
        assert_eq!(second, json!(4));
    }
}
