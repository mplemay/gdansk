use std::{collections::HashSet, fs};

use deno_core::{JsRuntime, PollEventLoopOptions, RuntimeOptions, serde_json::Value, serde_v8, v8};
use pyo3::{
    exceptions::{PyNotImplementedError, PyRuntimeError, PyTypeError, PyValueError},
    prelude::*,
    types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyModule, PyString, PyTuple, PyType},
};

#[derive(Debug)]
enum ScriptRuntimeError {
    Execution(String),
    Deserialize(String),
}

impl ScriptRuntimeError {
    fn execution(message: impl Into<String>) -> Self {
        Self::Execution(message.into())
    }

    fn deserialize(message: impl Into<String>) -> Self {
        Self::Deserialize(message.into())
    }
}

struct JsContext {
    default_function: v8::Global<v8::Function>,
    js_runtime: JsRuntime,
    tokio_runtime: tokio::runtime::Runtime,
}

#[pyclass(module = "gdansk_runtime._core", frozen, skip_from_py_object)]
struct Script {
    contents: String,
    inputs: Py<PyAny>,
    outputs: Py<PyAny>,
}

#[pyclass(module = "gdansk_runtime._core", frozen, skip_from_py_object)]
struct Runtime;

#[pyclass(module = "gdansk_runtime._core", unsendable, skip_from_py_object)]
struct RuntimeContext {
    script: Py<Script>,
    context: Option<JsContext>,
}

fn execution_error(err: impl std::fmt::Debug) -> ScriptRuntimeError {
    ScriptRuntimeError::execution(format!("Execution error: {err:?}"))
}

fn map_runtime_error(err: ScriptRuntimeError) -> PyErr {
    match err {
        ScriptRuntimeError::Execution(message) => PyRuntimeError::new_err(message),
        ScriptRuntimeError::Deserialize(message) => PyValueError::new_err(message),
    }
}

fn py_any_to_json_value(
    value: &Bound<'_, PyAny>,
    message: &'static str,
) -> PyResult<deno_core::serde_json::Value> {
    let mut seen = HashSet::new();
    py_any_to_json_value_inner(value, &mut seen, message)
}

fn py_any_to_json_value_inner(
    value: &Bound<'_, PyAny>,
    seen: &mut HashSet<usize>,
    message: &'static str,
) -> PyResult<deno_core::serde_json::Value> {
    if value.is_none() {
        return Ok(deno_core::serde_json::Value::Null);
    }

    if value.is_instance_of::<PyBool>() {
        return Ok(deno_core::serde_json::Value::Bool(
            value.cast::<PyBool>()?.extract::<bool>()?,
        ));
    }

    if value.is_instance_of::<PyString>() {
        return Ok(deno_core::serde_json::Value::String(
            value.cast::<PyString>()?.to_str()?.to_owned(),
        ));
    }

    if value.is_instance_of::<PyInt>() {
        let integer = value.cast::<PyInt>()?;
        if let Ok(integer) = integer.extract::<i64>() {
            return Ok(deno_core::serde_json::Value::Number(integer.into()));
        }
        if let Ok(integer) = integer.extract::<u64>() {
            return Ok(deno_core::serde_json::Value::Number(integer.into()));
        }
        return Err(PyTypeError::new_err(message));
    }

    if value.is_instance_of::<PyFloat>() {
        let number = value.cast::<PyFloat>()?.extract::<f64>()?;
        let Some(number) = deno_core::serde_json::Number::from_f64(number) else {
            return Err(PyTypeError::new_err(message));
        };
        return Ok(deno_core::serde_json::Value::Number(number));
    }

    if value.is_instance_of::<PyDict>() {
        let dict = value.cast::<PyDict>()?;
        let object_id = dict.as_ptr() as usize;
        if !seen.insert(object_id) {
            return Err(PyTypeError::new_err(message));
        }
        let mut entries = deno_core::serde_json::Map::new();
        for (key, item) in dict.iter() {
            let key = key
                .cast::<PyString>()
                .map_err(|_| PyTypeError::new_err(message))?
                .to_str()
                .map_err(|_| PyTypeError::new_err(message))?
                .to_owned();
            entries.insert(key, py_any_to_json_value_inner(&item, seen, message)?);
        }
        seen.remove(&object_id);
        return Ok(deno_core::serde_json::Value::Object(entries));
    }

    if value.is_instance_of::<PyList>() {
        let list = value.cast::<PyList>()?;
        let object_id = list.as_ptr() as usize;
        if !seen.insert(object_id) {
            return Err(PyTypeError::new_err(message));
        }
        let items = deno_core::serde_json::Value::Array(
            list.iter()
                .map(|item| py_any_to_json_value_inner(&item, seen, message))
                .collect::<PyResult<Vec<_>>>()?,
        );
        seen.remove(&object_id);
        return Ok(items);
    }

    if value.is_instance_of::<PyTuple>() {
        let tuple = value.cast::<PyTuple>()?;
        let object_id = tuple.as_ptr() as usize;
        if !seen.insert(object_id) {
            return Err(PyTypeError::new_err(message));
        }
        let items = deno_core::serde_json::Value::Array(
            tuple
                .iter()
                .map(|item| py_any_to_json_value_inner(&item, seen, message))
                .collect::<PyResult<Vec<_>>>()?,
        );
        seen.remove(&object_id);
        return Ok(items);
    }

    Err(PyTypeError::new_err(message))
}

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

fn read_json_value(
    runtime: &mut JsRuntime,
    output: v8::Global<v8::Value>,
) -> Result<Value, ScriptRuntimeError> {
    deno_core::scope!(scope, runtime);
    let local = v8::Local::new(scope, output);
    if local.is_number() {
        let Some(number) = local.number_value(scope) else {
            return Err(ScriptRuntimeError::deserialize(
                "Cannot deserialize value: unsupported JavaScript value",
            ));
        };
        if !number.is_finite() {
            return Err(ScriptRuntimeError::deserialize(
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
        return Err(ScriptRuntimeError::deserialize(
            "Cannot deserialize value: unsupported JavaScript value",
        ));
    }
    serde_v8::from_v8::<Value>(scope, local).map_err(|err| {
        ScriptRuntimeError::deserialize(format!("Cannot deserialize value: {err:?}"))
    })
}

async fn load_default_function(
    runtime: &mut JsRuntime,
    code: &str,
) -> Result<v8::Global<v8::Function>, ScriptRuntimeError> {
    let module_specifier =
        deno_core::resolve_url("file:///gdansk-runtime/script.js").map_err(execution_error)?;
    let mod_id = runtime
        .load_main_es_module_from_code(&module_specifier, code.to_owned())
        .await
        .map_err(execution_error)?;

    let evaluation = runtime.mod_evaluate(mod_id);
    runtime
        .run_event_loop(PollEventLoopOptions::default())
        .await
        .map_err(execution_error)?;
    evaluation.await.map_err(execution_error)?;

    let namespace = runtime
        .get_module_namespace(mod_id)
        .map_err(execution_error)?;
    deno_core::scope!(scope, runtime);
    let namespace = v8::Local::new(scope, namespace);
    let key = v8::String::new(scope, "default")
        .ok_or_else(|| ScriptRuntimeError::execution("Failed to read script default export"))?;
    let Some(value) = namespace.get(scope, key.into()) else {
        return Err(ScriptRuntimeError::execution(
            "Script default export is missing",
        ));
    };
    if value.is_undefined() {
        return Err(ScriptRuntimeError::execution(
            "Script default export is missing",
        ));
    }
    let function = v8::Local::<v8::Function>::try_from(value)
        .map_err(|_| ScriptRuntimeError::execution("Script default export must be a function"))?;
    Ok(v8::Global::new(scope, function))
}

impl JsContext {
    fn new(code: &str) -> Result<Self, ScriptRuntimeError> {
        let tokio_runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(execution_error)?;
        let mut js_runtime = JsRuntime::new(RuntimeOptions::default());
        let default_function =
            tokio_runtime.block_on(load_default_function(&mut js_runtime, code))?;
        Ok(Self {
            default_function,
            js_runtime,
            tokio_runtime,
        })
    }

    fn call(&mut self, input: Value) -> Result<Value, ScriptRuntimeError> {
        let argument = {
            deno_core::scope!(scope, &mut self.js_runtime);
            let local = serde_v8::to_v8(scope, input).map_err(|err| {
                ScriptRuntimeError::deserialize(format!("Cannot serialize input value: {err:?}"))
            })?;
            v8::Global::new(scope, local)
        };
        let arguments = [argument];
        let future = self
            .js_runtime
            .call_with_args(&self.default_function, &arguments);
        let output = self
            .tokio_runtime
            .block_on(
                self.js_runtime
                    .with_event_loop_promise(future, PollEventLoopOptions::default()),
            )
            .map_err(execution_error)?;
        read_json_value(&mut self.js_runtime, output)
    }
}

impl Script {
    fn normalize_type_adapter(
        py: Python<'_>,
        value: Py<PyAny>,
        type_adapter: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        if value.bind(py).is_instance(type_adapter)? {
            return Ok(value);
        }

        Ok(type_adapter.call1((value.bind(py),))?.unbind())
    }

    fn normalize_path(py: Python<'_>, path: &Bound<'_, PyAny>) -> PyResult<String> {
        let os = PyModule::import(py, "os")?;
        os.getattr("fspath")?.call1((path,))?.extract()
    }

    fn read_contents_from_path(py: Python<'_>, path: &Bound<'_, PyAny>) -> PyResult<String> {
        let path = Self::normalize_path(py, path)?;
        fs::read_to_string(path).map_err(PyErr::from)
    }

    fn serialize_input(&self, py: Python<'_>, input: &Bound<'_, PyAny>) -> PyResult<Value> {
        let validated = self.inputs.bind(py).call_method1("validate_python", (input,))?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("mode", "json")?;
        let dumped = self
            .inputs
            .bind(py)
            .call_method("dump_python", (validated,), Some(&kwargs))?;
        py_any_to_json_value(
            &dumped,
            "Script input must serialize to JSON-compatible Python values",
        )
    }

    fn validate_output<'py>(
        &self,
        py: Python<'py>,
        output: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.outputs
            .bind(py)
            .call_method1("validate_python", (output.bind(py),))
    }
}

impl RuntimeContext {
    fn new(script: Py<Script>) -> Self {
        Self {
            script,
            context: None,
        }
    }

    fn enter(&mut self, py: Python<'_>) -> PyResult<()> {
        if self.context.is_some() {
            return Err(PyRuntimeError::new_err("RuntimeContext is already active"));
        }
        let contents = {
            let script = self.script.bind(py).borrow();
            script.contents.clone()
        };
        let context = JsContext::new(&contents).map_err(map_runtime_error)?;
        self.context = Some(context);
        Ok(())
    }

    fn active_context(&mut self) -> PyResult<&mut JsContext> {
        self.context
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("RuntimeContext is not active"))
    }
}

#[pymethods]
impl Script {
    #[new]
    fn new(
        py: Python<'_>,
        contents: String,
        inputs: Py<PyAny>,
        outputs: Py<PyAny>,
    ) -> PyResult<Self> {
        if contents.trim().is_empty() {
            return Err(PyValueError::new_err("Script.contents must not be empty"));
        }

        let pydantic = PyModule::import(py, "pydantic")?;
        let type_adapter = pydantic.getattr("TypeAdapter")?;
        let inputs = Self::normalize_type_adapter(py, inputs, &type_adapter)?;
        let outputs = Self::normalize_type_adapter(py, outputs, &type_adapter)?;

        Ok(Self {
            contents,
            inputs,
            outputs,
        })
    }

    #[classmethod]
    fn from_file(
        _cls: &Bound<'_, PyType>,
        path: &Bound<'_, PyAny>,
        inputs: Py<PyAny>,
        outputs: Py<PyAny>,
    ) -> PyResult<Self> {
        let py = path.py();
        let contents = Self::read_contents_from_path(py, path)?;
        Self::new(py, contents, inputs, outputs)
    }

    #[getter]
    fn contents(&self) -> &str {
        &self.contents
    }

    #[getter]
    fn inputs(&self, py: Python<'_>) -> Py<PyAny> {
        self.inputs.clone_ref(py)
    }

    #[getter]
    fn outputs(&self, py: Python<'_>) -> Py<PyAny> {
        self.outputs.clone_ref(py)
    }
}

#[pymethods]
impl Runtime {
    #[new]
    #[pyo3(signature = (*, dependencies = None))]
    fn new(dependencies: Option<Py<PyAny>>) -> PyResult<Self> {
        if dependencies.is_some() {
            return Err(PyNotImplementedError::new_err(
                "Runtime dependencies are not implemented yet",
            ));
        }
        Ok(Self)
    }

    fn __call__(&self, script: Py<Script>) -> RuntimeContext {
        RuntimeContext::new(script)
    }
}

#[pymethods]
impl RuntimeContext {
    fn __enter__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<Self>> {
        slf.borrow_mut(py).enter(py)?;
        Ok(slf)
    }

    fn __exit__(
        &mut self,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) {
        self.context = None;
    }

    fn __call__<'py>(
        &mut self,
        py: Python<'py>,
        input: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input_json = {
            let script = self.script.bind(py).borrow();
            script.serialize_input(py, input)?
        };
        let output_json = self
            .active_context()?
            .call(input_json)
            .map_err(map_runtime_error)?;
        let output = json_to_py(py, &output_json)?;
        let script = self.script.bind(py).borrow();
        script.validate_output(py, output)
    }
}

#[pymodule]
mod _core {
    #[pymodule_export]
    use super::{Runtime, RuntimeContext, Script};
}
