use std::{
    collections::HashSet,
    fs,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, SyncSender},
    },
    thread::{self, JoinHandle},
};

use deno_core::{JsRuntime, PollEventLoopOptions, RuntimeOptions, serde_json::Value, serde_v8, v8};
use pyo3::{
    exceptions::{PyRuntimeError, PyTypeError, PyValueError},
    prelude::*,
    types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyModule, PyString, PyTuple, PyType},
};
use tokio::sync::oneshot;

mod runtime_npm;

use runtime_npm::{RuntimeNpm, RuntimeNpmError};

const RUNTIME_CONTEXT_ALREADY_ACTIVE: &str = "RuntimeContext is already active";
const RUNTIME_CONTEXT_NOT_ACTIVE: &str = "RuntimeContext is not active";
const RUNTIME_PACKAGE_JSON_NOT_CONFIGURED: &str = "Runtime.package_json is not configured";

deno_core::extension!(
    gdansk_runtime_web_ext,
    esm_entry_point = "ext:gdansk_runtime_web_ext/runtime_web.js",
    esm = [
        dir "src",
        "runtime_web.js",
    ],
);

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

#[derive(Clone)]
struct AsyncWorkerClient {
    active: Arc<AtomicBool>,
    sender: mpsc::Sender<AsyncWorkerMessage>,
}

struct AsyncWorker {
    client: AsyncWorkerClient,
    join_handle: Option<JoinHandle<()>>,
}

enum AsyncWorkerMessage {
    Call {
        input: Value,
        reply: oneshot::Sender<Result<Value, ScriptRuntimeError>>,
    },
    Close {
        reply: SyncSender<()>,
    },
}

#[pyclass(module = "gdansk_runtime._core", frozen, skip_from_py_object)]
struct Script {
    contents: String,
    inputs: Py<PyAny>,
    outputs: Py<PyAny>,
}

#[pyclass(module = "gdansk_runtime._core", frozen, skip_from_py_object)]
struct Runtime {
    package_json: Option<PathBuf>,
}

#[pyclass(module = "gdansk_runtime._core", unsendable, skip_from_py_object)]
struct RuntimeContext {
    script: Py<Script>,
    context: Option<JsContext>,
    async_context: Option<AsyncWorker>,
}

#[pyclass(module = "gdansk_runtime._core", frozen, skip_from_py_object)]
struct AsyncRuntimeContext {
    script: Py<Script>,
    worker: AsyncWorkerClient,
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

fn map_runtime_npm_error(err: RuntimeNpmError) -> PyErr {
    PyRuntimeError::new_err(err.to_string())
}

fn normalize_runtime_path(py: Python<'_>, path: &Bound<'_, PyAny>) -> PyResult<PathBuf> {
    let path = PathBuf::from(Script::normalize_path(py, path)?);
    if path.is_absolute() {
        return Ok(path);
    }

    Ok(std::env::current_dir()?.join(path))
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
        let mut js_runtime = JsRuntime::new(RuntimeOptions {
            extensions: vec![
                deno_webidl::deno_webidl::init(),
                deno_web::deno_web::init(
                    Default::default(),
                    None,
                    deno_web::InMemoryBroadcastChannel::default(),
                ),
                gdansk_runtime_web_ext::init(),
            ],
            ..Default::default()
        });
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

impl AsyncWorkerClient {
    fn new(sender: mpsc::Sender<AsyncWorkerMessage>) -> Self {
        Self {
            active: Arc::new(AtomicBool::new(true)),
            sender,
        }
    }

    fn deactivate(&self) {
        self.active.store(false, Ordering::Release);
    }

    fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    async fn call(&self, input: Value) -> Result<Value, ScriptRuntimeError> {
        if !self.is_active() {
            return Err(ScriptRuntimeError::execution(RUNTIME_CONTEXT_NOT_ACTIVE));
        }

        let (reply, response) = oneshot::channel();
        self.sender
            .send(AsyncWorkerMessage::Call { input, reply })
            .map_err(|_| ScriptRuntimeError::execution(RUNTIME_CONTEXT_NOT_ACTIVE))?;

        response
            .await
            .map_err(|_| ScriptRuntimeError::execution(RUNTIME_CONTEXT_NOT_ACTIVE))?
    }
}

impl AsyncWorker {
    fn spawn(code: String) -> Result<Self, ScriptRuntimeError> {
        let (sender, receiver) = mpsc::channel();
        let client = AsyncWorkerClient::new(sender);
        let (ready, initialized) = mpsc::sync_channel(1);
        let join_handle = thread::spawn(move || {
            let mut context = match JsContext::new(&code) {
                Ok(context) => {
                    let _ = ready.send(Ok(()));
                    context
                }
                Err(err) => {
                    let _ = ready.send(Err(err));
                    return;
                }
            };

            while let Ok(message) = receiver.recv() {
                match message {
                    AsyncWorkerMessage::Call { input, reply } => {
                        let _ = reply.send(context.call(input));
                    }
                    AsyncWorkerMessage::Close { reply } => {
                        let _ = reply.send(());
                        break;
                    }
                }
            }
        });

        match initialized.recv() {
            Ok(Ok(())) => Ok(Self {
                client,
                join_handle: Some(join_handle),
            }),
            Ok(Err(err)) => {
                let _ = join_handle.join();
                Err(err)
            }
            Err(_) => {
                let _ = join_handle.join();
                Err(ScriptRuntimeError::execution(
                    "Async runtime worker failed to initialize",
                ))
            }
        }
    }

    fn client(&self) -> AsyncWorkerClient {
        self.client.clone()
    }

    fn deactivate(&self) {
        self.client.deactivate();
    }

    fn close(mut self) -> Result<(), ScriptRuntimeError> {
        self.deactivate();

        if let Some(join_handle) = self.join_handle.take() {
            let (reply, response) = mpsc::sync_channel(1);
            if self
                .client
                .sender
                .send(AsyncWorkerMessage::Close { reply })
                .is_ok()
            {
                let _ = response.recv();
            }

            join_handle
                .join()
                .map_err(|_| ScriptRuntimeError::execution("Async runtime worker panicked"))?;
        }

        Ok(())
    }
}

impl Script {
    fn build_type_adapter(
        py: Python<'_>,
        value_type: Py<PyAny>,
        type_adapter: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        Ok(type_adapter.call1((value_type.bind(py),))?.unbind())
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
        let validated = self
            .inputs
            .bind(py)
            .call_method1("validate_python", (input,))?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("mode", "json")?;
        let dumped =
            self.inputs
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

    fn deserialize_output<'py>(
        &self,
        py: Python<'py>,
        output: &Value,
    ) -> PyResult<Bound<'py, PyAny>> {
        let output = json_to_py(py, output)?;
        self.validate_output(py, output)
    }
}

impl RuntimeContext {
    fn new(script: Py<Script>) -> Self {
        Self {
            script,
            context: None,
            async_context: None,
        }
    }

    fn ensure_inactive(&self) -> PyResult<()> {
        if self.context.is_some() || self.async_context.is_some() {
            return Err(PyRuntimeError::new_err(RUNTIME_CONTEXT_ALREADY_ACTIVE));
        }

        Ok(())
    }

    fn enter(&mut self, py: Python<'_>) -> PyResult<()> {
        self.ensure_inactive()?;
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
            .ok_or_else(|| PyRuntimeError::new_err(RUNTIME_CONTEXT_NOT_ACTIVE))
    }

    fn activate_async_context(
        &mut self,
        worker: AsyncWorker,
        py: Python<'_>,
    ) -> PyResult<AsyncRuntimeContext> {
        self.ensure_inactive()?;

        let worker_client = worker.client();
        let script = self.script.clone_ref(py);
        self.async_context = Some(worker);

        Ok(AsyncRuntimeContext {
            script,
            worker: worker_client,
        })
    }

    fn take_async_context(&mut self) -> Option<AsyncWorker> {
        let worker = self.async_context.take();
        if let Some(worker) = &worker {
            worker.deactivate();
        }
        worker
    }
}

impl Runtime {
    fn package_manager(&self) -> PyResult<RuntimeNpm> {
        let package_json = self
            .package_json
            .clone()
            .ok_or_else(|| PyRuntimeError::new_err(RUNTIME_PACKAGE_JSON_NOT_CONFIGURED))?;
        Ok(RuntimeNpm::new(package_json))
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
        let inputs = Self::build_type_adapter(py, inputs, &type_adapter)?;
        let outputs = Self::build_type_adapter(py, outputs, &type_adapter)?;

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
    #[pyo3(signature = (*, package_json = None))]
    fn new(py: Python<'_>, package_json: Option<Py<PyAny>>) -> PyResult<Self> {
        let package_json = package_json
            .map(|path| normalize_runtime_path(py, path.bind(py)))
            .transpose()?;

        Ok(Self { package_json })
    }

    fn lock(&self) -> PyResult<()> {
        self.package_manager()?
            .lock()
            .map_err(map_runtime_npm_error)
    }

    fn alock<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let package_manager = self.package_manager()?;

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            tokio::task::spawn_blocking(move || package_manager.lock())
                .await
                .map_err(|err| map_runtime_error(execution_error(err)))?
                .map_err(map_runtime_npm_error)?;
            Python::attach(|py| Ok(py.None()))
        })
    }

    fn sync(&self) -> PyResult<()> {
        self.package_manager()?
            .sync()
            .map_err(map_runtime_npm_error)
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

    fn __aenter__<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_inactive()?;
        let contents = {
            let script = self.script.bind(py).borrow();
            script.contents.clone()
        };
        let worker = AsyncWorker::spawn(contents).map_err(map_runtime_error)?;
        let async_context = self.activate_async_context(worker, py)?;
        let async_context = Py::new(py, async_context)?;

        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(async_context) })
    }

    fn __exit__(
        &mut self,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) {
        self.context = None;
    }

    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let worker = self.take_async_context();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            if let Some(worker) = worker {
                tokio::task::spawn_blocking(move || worker.close())
                    .await
                    .map_err(|err| map_runtime_error(execution_error(err)))?
                    .map_err(map_runtime_error)?;
            }

            Python::attach(|py| Ok(py.None()))
        })
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
        let script = self.script.bind(py).borrow();
        script.deserialize_output(py, &output_json)
    }
}

#[pymethods]
impl AsyncRuntimeContext {
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        input: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        if !self.worker.is_active() {
            return Err(PyRuntimeError::new_err(RUNTIME_CONTEXT_NOT_ACTIVE));
        }

        let input_json = {
            let script = self.script.bind(py).borrow();
            script.serialize_input(py, input)?
        };
        let script = self.script.clone_ref(py);
        let worker = self.worker.clone();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let output_json = worker.call(input_json).await.map_err(map_runtime_error)?;

            Python::attach(|py| {
                let script = script.bind(py).borrow();
                script
                    .deserialize_output(py, &output_json)
                    .map(Bound::unbind)
            })
        })
    }
}

#[pymodule]
mod _core {
    #[pymodule_export]
    use super::{AsyncRuntimeContext, Runtime, RuntimeContext, Script};
}
