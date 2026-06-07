use std::{
    borrow::Cow,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    rc::Rc,
    sync::{Arc, Mutex, mpsc},
    thread,
    time::Duration,
};

use deno_core::{
    FastString, ModuleSpecifier,
    anyhow::{Context, anyhow},
    error::AnyError,
};
use deno_error::JsErrorBox;
use deno_media_type::MediaType;
use deno_resolver::npm::{DenoInNpmPackageChecker, NpmResolver};
use deno_runtime::{
    BootstrapOptions, FeatureChecker, WorkerExecutionMode,
    deno_fs::RealFs,
    deno_node::{NodeExtInitServices, NodeRequireLoader, NodeRequireLoaderRc},
    deno_permissions::{PermissionsContainer, RuntimePermissionDescriptorParser},
    deno_web::{BlobStore, InMemoryBroadcastChannel},
    worker::{MainWorker, WorkerOptions, WorkerServiceOptions},
};
use sys_traits::impls::RealSys;

use crate::{
    embed::prepare_package_runtime,
    embed::sys::EmbedSys,
    packages::PackageEnvironment,
    runtime::module_loader::{self, PackageAwareModuleLoader},
};

pub(crate) async fn build_frontend(root: PathBuf, build_directory: String) -> Result<(), AnyError> {
    let main_module = frontend_module(&root, "__gdansk_vite_build__.ts")?;
    let source = vite_build_source(&root, &build_directory)?;
    let mut worker = create_frontend_worker(
        root,
        main_module.clone(),
        source,
        vec!["vite".to_string(), "build".to_string()],
    )
    .await?;

    worker
        .execute_main_module(&main_module)
        .await
        .map_err(|error| anyhow!("Failed to execute embedded Vite build: {error:?}"))?;
    worker
        .run_event_loop(false)
        .await
        .map_err(|error| anyhow!("Embedded Vite build event loop failed: {error:?}"))?;
    Ok(())
}

pub(crate) fn build_frontend_blocking(
    root: PathBuf,
    build_directory: String,
) -> Result<(), AnyError> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("Failed to create embedded Vite runtime")?;
    runtime.block_on(build_frontend(root, build_directory))
}

#[derive(Debug)]
pub(crate) struct FrontendDevServer {
    control_addr: SocketAddr,
    join_handle: Mutex<Option<thread::JoinHandle<Result<(), String>>>>,
    origin: String,
}

impl FrontendDevServer {
    pub(crate) fn origin(&self) -> &str {
        &self.origin
    }

    pub(crate) fn stop_blocking(&self) -> Result<(), AnyError> {
        let join_handle = self
            .join_handle
            .lock()
            .expect("frontend dev-server join handle lock should not be poisoned")
            .take();
        let Some(join_handle) = join_handle else {
            return Ok(());
        };

        let _ = request_shutdown(self.control_addr);
        join_handle
            .join()
            .map_err(|_| anyhow!("Embedded Vite dev-server worker panicked"))?
            .map_err(|error| anyhow!(error))?;
        Ok(())
    }
}

impl Drop for FrontendDevServer {
    fn drop(&mut self) {
        if let Some(join_handle) = self
            .join_handle
            .lock()
            .expect("frontend dev-server join handle lock should not be poisoned")
            .take()
        {
            let _ = request_shutdown(self.control_addr);
            let _ = join_handle.join();
        }
    }
}

enum FrontendDevStart {
    Ready,
    Failed(String),
}

pub(crate) fn start_frontend_dev(
    root: PathBuf,
    host: String,
    port: u16,
) -> Result<FrontendDevServer, AnyError> {
    let control_listener = TcpListener::bind(("127.0.0.1", 0))
        .context("Failed to reserve embedded Vite control port")?;
    let control_addr = control_listener
        .local_addr()
        .context("Failed to read embedded Vite control address")?;
    drop(control_listener);

    let origin = format!("http://{host}:{port}");
    let (ready_sender, ready_receiver) = mpsc::channel();
    let join_handle = thread::spawn(move || {
        run_frontend_dev_thread(root, host, port, control_addr.port(), ready_sender)
    });

    match ready_receiver
        .recv()
        .context("Embedded Vite dev-server worker stopped before startup")?
    {
        FrontendDevStart::Ready => Ok(FrontendDevServer {
            control_addr,
            join_handle: Mutex::new(Some(join_handle)),
            origin,
        }),
        FrontendDevStart::Failed(error) => {
            let _ = join_handle.join();
            Err(anyhow!(error))
        }
    }
}

fn run_frontend_dev_thread(
    root: PathBuf,
    host: String,
    port: u16,
    control_port: u16,
    ready_sender: mpsc::Sender<FrontendDevStart>,
) -> Result<(), String> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|error| format!("Failed to create embedded Vite dev runtime: {error}"))?;
    let main_module =
        frontend_module(&root, "__gdansk_vite_dev__.ts").map_err(|error| error.to_string())?;
    let source =
        vite_dev_source(&root, &host, port, control_port).map_err(|error| error.to_string())?;
    let mut worker = match runtime.block_on(create_frontend_worker(
        root,
        main_module.clone(),
        source,
        vec![
            "vite".to_string(),
            "--host".to_string(),
            host,
            "--port".to_string(),
            port.to_string(),
        ],
    )) {
        Ok(worker) => worker,
        Err(error) => {
            let message = error.to_string();
            let _ = ready_sender.send(FrontendDevStart::Failed(message.clone()));
            return Err(message);
        }
    };

    if let Err(error) = runtime.block_on(worker.execute_main_module(&main_module)) {
        let message = format!("Failed to execute embedded Vite dev server: {error:?}");
        let _ = ready_sender.send(FrontendDevStart::Failed(message.clone()));
        return Err(message);
    }

    let _ = ready_sender.send(FrontendDevStart::Ready);
    runtime
        .block_on(worker.run_event_loop(false))
        .map_err(|error| format!("Embedded Vite dev-server event loop failed: {error}"))
}

async fn create_frontend_worker(
    root: PathBuf,
    main_module: ModuleSpecifier,
    source: String,
    args: Vec<String>,
) -> Result<MainWorker, AnyError> {
    let package_environment = PackageEnvironment::from_imports(
        root.clone(),
        vec![("vite".to_string(), "npm:vite".to_string())],
    )?;
    let context = package_environment.embed_context()?;
    let state = Rc::new(prepare_package_runtime(context, main_module.clone(), source).await?);
    let services = create_worker_services(state, root)?;
    Ok(MainWorker::bootstrap_from_options(
        &main_module,
        services,
        WorkerOptions {
            bootstrap: BootstrapOptions {
                args,
                location: Some(main_module.clone()),
                mode: WorkerExecutionMode::Run,
                ..Default::default()
            },
            residual_lazy_esm_sources: deno_snapshots::RESIDUAL_LAZY_ESM,
            residual_lazy_js_sources: deno_snapshots::RESIDUAL_LAZY_JS,
            startup_snapshot: deno_snapshots::CLI_SNAPSHOT,
            ..Default::default()
        },
    ))
}

fn create_worker_services(
    state: Rc<crate::embed::PackageRuntimeState>,
    root: PathBuf,
) -> Result<WorkerServiceOptions<DenoInNpmPackageChecker, NpmResolver<EmbedSys>, EmbedSys>, AnyError>
{
    let module_loader = Rc::new(PackageAwareModuleLoader::new(state.clone(), root));
    let resolver_factory = state.context.resolver_factory();
    let permission_parser = Arc::new(RuntimePermissionDescriptorParser::new(RealSys));
    let permissions = PermissionsContainer::allow_all(permission_parser);
    let node_require_loader: NodeRequireLoaderRc = Rc::new(FrontendNodeRequireLoader {
        cjs_tracker: resolver_factory.cjs_tracker()?.clone(),
    });
    let node_services = NodeExtInitServices {
        node_require_loader,
        node_resolver: resolver_factory.node_resolver()?.clone(),
        pkg_json_resolver: resolver_factory.pkg_json_resolver().clone(),
        sys: EmbedSys::default(),
    };
    Ok(WorkerServiceOptions {
        blob_store: Arc::new(BlobStore::default()),
        broadcast_channel: InMemoryBroadcastChannel::default(),
        deno_rt_native_addon_loader: None,
        feature_checker: Arc::new(FeatureChecker::default()),
        fs: Arc::new(RealFs),
        module_loader,
        node_services: Some(node_services),
        npm_process_state_provider: None,
        permissions,
        root_cert_store_provider: None,
        fetch_dns_resolver: Default::default(),
        shared_array_buffer_store: None,
        compiled_wasm_module_store: None,
        v8_code_cache: None,
        bundle_provider: None,
    })
}

#[derive(Debug)]
struct FrontendNodeRequireLoader {
    cjs_tracker: deno_resolver::cjs::CjsTrackerRc<DenoInNpmPackageChecker, EmbedSys>,
}

impl NodeRequireLoader for FrontendNodeRequireLoader {
    fn ensure_read_permission<'a>(
        &self,
        _permissions: &mut PermissionsContainer,
        path: Cow<'a, Path>,
    ) -> Result<Cow<'a, Path>, JsErrorBox> {
        Ok(path)
    }

    fn load_text_file_lossy(&self, path: &Path) -> Result<FastString, JsErrorBox> {
        let text = std::fs::read_to_string(path)
            .or_else(|error| {
                if error.kind() == std::io::ErrorKind::InvalidData {
                    std::fs::read(path).map(|bytes| String::from_utf8_lossy(&bytes).into_owned())
                } else {
                    Err(error)
                }
            })
            .map_err(JsErrorBox::from_err)?;
        if MediaType::from_path(path).is_emittable() {
            let specifier =
                deno_path_util::url_from_file_path(path).map_err(JsErrorBox::from_err)?;
            let emitted = module_loader::maybe_transpile_source(&specifier, text)
                .map_err(JsErrorBox::from_err)?;
            Ok(emitted.into())
        } else {
            Ok(text.into())
        }
    }

    fn is_maybe_cjs(
        &self,
        specifier: &ModuleSpecifier,
    ) -> Result<bool, node_resolver::errors::PackageJsonLoadError> {
        let media_type = MediaType::from_specifier(specifier);
        self.cjs_tracker.is_maybe_cjs(specifier, media_type)
    }

    fn is_maybe_cjs_from_require(
        &self,
        specifier: &ModuleSpecifier,
    ) -> Result<bool, node_resolver::errors::PackageJsonLoadError> {
        let media_type = MediaType::from_specifier(specifier);
        self.cjs_tracker
            .is_maybe_cjs_from_require(specifier, media_type)
    }
}

fn frontend_module(root: &Path, name: &str) -> Result<ModuleSpecifier, AnyError> {
    ModuleSpecifier::from_file_path(root.join(name))
        .map_err(|_| anyhow!("Could not create Vite module URL"))
}

fn request_shutdown(control_addr: SocketAddr) -> Result<(), AnyError> {
    let mut stream = TcpStream::connect_timeout(&control_addr, Duration::from_secs(2))
        .context("Failed to connect to embedded Vite control server")?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .context("Failed to configure embedded Vite control read timeout")?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .context("Failed to configure embedded Vite control write timeout")?;
    let request = "POST /shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n";
    stream
        .write_all(request.as_bytes())
        .context("Failed to request embedded Vite shutdown")?;
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    if !response.starts_with("HTTP/1.1 200") && !response.starts_with("HTTP/1.0 200") {
        return Err(anyhow!(
            "Embedded Vite shutdown returned an unexpected response"
        ));
    }
    Ok(())
}

fn vite_build_source(root: &Path, build_directory: &str) -> Result<String, AnyError> {
    let root = serde_json::to_string(&root.to_string_lossy())?;
    let build_directory = serde_json::to_string(build_directory)?;
    Ok(format!(
        r#"import {{ build }} from "vite";

Deno.chdir({root});
await build({{
  build: {{
    manifest: false,
    outDir: {build_directory},
  }},
}});
"#
    ))
}

fn vite_dev_source(
    root: &Path,
    host: &str,
    port: u16,
    control_port: u16,
) -> Result<String, AnyError> {
    let root = serde_json::to_string(&root.to_string_lossy())?;
    let host = serde_json::to_string(host)?;
    Ok(format!(
        r#"import {{ createServer }} from "vite";

Deno.chdir({root});
const server = await createServer({{
  server: {{
    host: {host},
    port: {port},
    strictPort: true,
  }},
}});

await server.listen();

const control = Deno.serve({{
  hostname: "127.0.0.1",
  onListen() {{}},
  port: {control_port},
}}, (request) => {{
  const url = new URL(request.url);
  if (request.method !== "POST" || url.pathname !== "/shutdown") {{
    return new Response("not found", {{ status: 404 }});
  }}

  queueMicrotask(() => {{
    Promise.resolve()
      .then(() => server.close())
      .then(() => control.shutdown())
      .catch((error) => console.error(error));
  }});
  return new Response("ok");
}});
"#
    ))
}
