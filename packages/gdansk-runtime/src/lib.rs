use std::{
    collections::HashSet,
    ffi::OsStr,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, SyncSender},
    },
    thread::{self, JoinHandle},
    time::Duration,
};

use deno_core::{
    JsRuntime, ModuleLoadOptions, ModuleLoadReferrer, ModuleLoadResponse, ModuleLoader,
    ModuleSource, ModuleSourceCode, ModuleSpecifier, ModuleType, PollEventLoopOptions,
    ResolutionKind, RuntimeOptions, op2, serde_json::Value, serde_v8, v8,
};
use deno_error::JsErrorBox;
use oxc_resolver::{ResolveOptions, Resolver};
use pyo3::{
    exceptions::{PyRuntimeError, PyTypeError, PyValueError},
    prelude::*,
    types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple},
};
use tokio::sync::oneshot;
use url::Url;

mod runtime_npm;

use runtime_npm::{RuntimeNpm, RuntimeNpmError};

const RUNTIME_CONTEXT_ALREADY_ACTIVE: &str = "RuntimeContext is already active";
const RUNTIME_CONTEXT_NOT_ACTIVE: &str = "RuntimeContext is not active";
const RUNTIME_PACKAGE_JSON_NOT_CONFIGURED: &str = "Runtime.package_json is not configured";

#[op2]
async fn op_gdansk_runtime_sleep(delay_ms: u32) {
    tokio::time::sleep(Duration::from_millis(u64::from(delay_ms))).await;
}

deno_core::extension!(
    gdansk_runtime_web_ext,
    ops = [op_gdansk_runtime_sleep],
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

impl ScriptModuleLoader {
    fn new(root_dir: PathBuf) -> Self {
        Self {
            root_dir,
            resolver: Resolver::new(
                ResolveOptions::default().with_condition_names(&["node", "import", "default"]),
            ),
        }
    }

    fn resolve_input_path(&self, input: &str) -> Result<PathBuf, JsErrorBox> {
        if input.starts_with("file://") {
            let specifier =
                ModuleSpecifier::parse(input).map_err(|err| JsErrorBox::generic(err.to_string()))?;
            return specifier
                .to_file_path()
                .map_err(|_| JsErrorBox::generic(format!("unsupported file URL: {input}")));
        }

        let path = Path::new(input);
        if path.is_absolute() {
            return Ok(path.to_path_buf());
        }

        Ok(self.root_dir.join(path))
    }

    fn resolve_specifier(
        &self,
        specifier: &str,
        referrer: Option<&str>,
    ) -> Result<ModuleSpecifier, JsErrorBox> {
        if specifier.starts_with("node:") {
            return Err(unsupported_node_builtin(specifier));
        }

        if specifier.starts_with("file://") {
            return ModuleSpecifier::parse(specifier)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        let path = Path::new(specifier);
        if path.is_absolute() {
            return path_to_module_specifier(&canonicalize_existing_file(path)?);
        }

        if is_relative_specifier(specifier) {
            let base_dir = referrer
                .map(|value| {
                    self.resolve_input_path(value).map(|path| {
                        if path.is_dir() {
                            path
                        } else {
                            path.parent().unwrap_or(path.as_path()).to_path_buf()
                        }
                    })
                })
                .transpose()?
                .unwrap_or_else(|| self.root_dir.clone());
            return path_to_module_specifier(&canonicalize_existing_file(&base_dir.join(specifier))?);
        }

        let base_dir = referrer
            .map(|value| {
                self.resolve_input_path(value).map(|path| {
                    if path.is_dir() {
                        path
                    } else {
                        path.parent().unwrap_or(path.as_path()).to_path_buf()
                    }
                })
            })
            .transpose()?
            .unwrap_or_else(|| self.root_dir.clone());
        let resolution = self
            .resolver
            .resolve(&base_dir, specifier)
            .map_err(|err| JsErrorBox::generic(err.to_string()))?;
        let resolved = resolution.path().to_path_buf();
        if !resolved.is_file() {
            return Err(JsErrorBox::generic(format!(
                "resolved module is not a file: {}",
                resolved.display()
            )));
        }

        path_to_module_specifier(&resolved)
    }
}

impl ModuleLoader for ScriptModuleLoader {
    fn resolve(
        &self,
        specifier: &str,
        referrer: &str,
        _kind: ResolutionKind,
    ) -> Result<ModuleSpecifier, JsErrorBox> {
        self.resolve_specifier(specifier, Some(referrer))
    }

    fn load(
        &self,
        module_specifier: &ModuleSpecifier,
        _maybe_referrer: Option<&ModuleLoadReferrer>,
        _options: ModuleLoadOptions,
    ) -> ModuleLoadResponse {
        let result = (|| {
            if module_specifier.scheme() == "node" {
                return Err(unsupported_node_builtin(module_specifier.as_str()));
            }

            let path = module_specifier.to_file_path().map_err(|_| {
                JsErrorBox::generic(format!("unsupported module specifier: {module_specifier}"))
            })?;
            let code = fs::read_to_string(&path).map_err(|err| JsErrorBox::generic(err.to_string()))?;
            let module_type = if path.extension() == Some(OsStr::new("json")) {
                ModuleType::Json
            } else {
                ModuleType::JavaScript
            };

            Ok(ModuleSource::new(
                module_type,
                ModuleSourceCode::String(code.into()),
                module_specifier,
                None,
            ))
        })();

        ModuleLoadResponse::Sync(result)
    }
}

struct JsContext {
    default_function: v8::Global<v8::Function>,
    js_runtime: JsRuntime,
    tokio_runtime: tokio::runtime::Runtime,
}

struct ScriptModuleLoader {
    root_dir: PathBuf,
    resolver: Resolver,
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

#[pyclass(module = "gdansk_runtime._core", frozen, subclass, skip_from_py_object)]
struct Script {
    contents: String,
}

#[pyclass(module = "gdansk_runtime._core", frozen, subclass, skip_from_py_object)]
struct Runtime {
    package_json: Option<PathBuf>,
}

#[pyclass(module = "gdansk_runtime._core", unsendable, subclass, skip_from_py_object)]
struct RuntimeContext {
    contents: String,
    entry_path: PathBuf,
    root_path: PathBuf,
    context: Option<JsContext>,
}

#[pyclass(module = "gdansk_runtime._core", subclass, skip_from_py_object)]
struct AsyncRuntimeContext {
    contents: String,
    entry_path: PathBuf,
    root_path: PathBuf,
    worker: Option<AsyncWorker>,
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

fn is_relative_specifier(specifier: &str) -> bool {
    specifier.starts_with("./") || specifier.starts_with("../")
}

fn unsupported_node_builtin(specifier: &str) -> JsErrorBox {
    JsErrorBox::generic(format!("unsupported node builtin module: {specifier}"))
}

fn canonicalize_existing_file(path: &Path) -> Result<PathBuf, JsErrorBox> {
    path.canonicalize()
        .map_err(|err| JsErrorBox::generic(err.to_string()))
}

fn path_to_module_specifier(path: &Path) -> Result<ModuleSpecifier, JsErrorBox> {
    let specifier = Url::from_file_path(path)
        .map_err(|_| JsErrorBox::generic(format!("failed to resolve path {}", path.display())))?
        .to_string();
    ModuleSpecifier::parse(&specifier).map_err(|err| JsErrorBox::generic(err.to_string()))
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
    entry_path: &Path,
) -> Result<v8::Global<v8::Function>, ScriptRuntimeError> {
    let module_specifier = path_to_module_specifier(entry_path)
        .map_err(|err| ScriptRuntimeError::execution(err.to_string()))?;
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
    fn new(code: &str, entry_path: &Path, root_path: &Path) -> Result<Self, ScriptRuntimeError> {
        let tokio_runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(execution_error)?;
        let module_loader = Rc::new(ScriptModuleLoader::new(root_path.to_path_buf()));
        let mut js_runtime = JsRuntime::new(RuntimeOptions {
            module_loader: Some(module_loader),
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
        let default_function = tokio_runtime.block_on(load_default_function(
            &mut js_runtime,
            code,
            entry_path,
        ))?;
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
        let default_function = self.default_function.clone();
        let output = self
            .tokio_runtime
            .block_on(async {
                let future = self.js_runtime.call_with_args(&default_function, &arguments);
                self.js_runtime
                    .with_event_loop_promise(future, PollEventLoopOptions::default())
                    .await
            })
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
    fn spawn(
        code: String,
        entry_path: PathBuf,
        root_path: PathBuf,
    ) -> Result<Self, ScriptRuntimeError> {
        let (sender, receiver) = mpsc::channel();
        let client = AsyncWorkerClient::new(sender);
        let (ready, initialized) = mpsc::sync_channel(1);
        let join_handle = thread::spawn(move || {
            let mut context = match JsContext::new(&code, &entry_path, &root_path) {
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

impl RuntimeContext {
    fn from_contents(contents: String, entry_path: PathBuf, root_path: PathBuf) -> Self {
        Self {
            contents,
            entry_path,
            root_path,
            context: None,
        }
    }

    fn ensure_inactive(&self) -> PyResult<()> {
        if self.context.is_some() {
            return Err(PyRuntimeError::new_err(RUNTIME_CONTEXT_ALREADY_ACTIVE));
        }

        Ok(())
    }

    fn enter(&mut self) -> PyResult<()> {
        self.ensure_inactive()?;
        let context = JsContext::new(&self.contents, &self.entry_path, &self.root_path)
            .map_err(map_runtime_error)?;
        self.context = Some(context);
        Ok(())
    }

    fn active_context(&mut self) -> PyResult<&mut JsContext> {
        self.context
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err(RUNTIME_CONTEXT_NOT_ACTIVE))
    }
}

impl AsyncRuntimeContext {
    fn from_contents(contents: String, entry_path: PathBuf, root_path: PathBuf) -> Self {
        Self {
            contents,
            entry_path,
            root_path,
            worker: None,
        }
    }

    fn ensure_inactive(&self) -> PyResult<()> {
        if self.worker.is_some() {
            return Err(PyRuntimeError::new_err(RUNTIME_CONTEXT_ALREADY_ACTIVE));
        }

        Ok(())
    }

    fn enter(&mut self) -> PyResult<()> {
        self.ensure_inactive()?;
        let worker = AsyncWorker::spawn(
            self.contents.clone(),
            self.entry_path.clone(),
            self.root_path.clone(),
        )
        .map_err(map_runtime_error)?;
        self.worker = Some(worker);
        Ok(())
    }

    fn active_worker(&self) -> PyResult<AsyncWorkerClient> {
        self.worker
            .as_ref()
            .map(AsyncWorker::client)
            .ok_or_else(|| PyRuntimeError::new_err(RUNTIME_CONTEXT_NOT_ACTIVE))
    }

    fn take_worker(&mut self) -> Option<AsyncWorker> {
        let worker = self.worker.take();
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
    fn new(contents: String) -> Self {
        Self { contents }
    }

    #[getter]
    fn contents(&self) -> &str {
        &self.contents
    }
}

#[pymethods]
impl Runtime {
    #[new]
    #[pyo3(signature = (*, package_json = None))]
    fn new(package_json: Option<String>) -> Self {
        Self {
            package_json: package_json.map(PathBuf::from),
        }
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
}

#[pymethods]
impl RuntimeContext {
    #[new]
    fn new(contents: String, entry_path: String, root_path: String) -> Self {
        Self::from_contents(contents, PathBuf::from(entry_path), PathBuf::from(root_path))
    }

    fn _ensure_inactive(&self) -> PyResult<()> {
        self.ensure_inactive()
    }

    fn __enter__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<Self>> {
        slf.borrow_mut(py).enter()?;
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
        let input_json = py_any_to_json_value(
            input,
            "RuntimeContext input must serialize to JSON-compatible Python values",
        )?;
        let output_json = self
            .active_context()?
            .call(input_json)
            .map_err(map_runtime_error)?;
        Ok(json_to_py(py, &output_json)?.into_bound(py))
    }
}

#[pymethods]
impl AsyncRuntimeContext {
    #[new]
    fn new(contents: String, entry_path: String, root_path: String) -> Self {
        Self::from_contents(contents, PathBuf::from(entry_path), PathBuf::from(root_path))
    }

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        slf.borrow_mut(py).enter()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf) })
    }

    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let worker = self.take_worker();

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
        &self,
        py: Python<'py>,
        input: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input_json = py_any_to_json_value(
            input,
            "AsyncRuntimeContext input must serialize to JSON-compatible Python values",
        )?;
        let worker = self.active_worker()?;

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let output_json = worker.call(input_json).await.map_err(map_runtime_error)?;

            Python::attach(|py| json_to_py(py, &output_json))
        })
    }
}

#[pymodule]
mod _core {
    #[pymodule_export]
    use super::{AsyncRuntimeContext, Runtime, RuntimeContext, Script};
}
