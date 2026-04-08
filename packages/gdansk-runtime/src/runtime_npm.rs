use std::{
    collections::HashMap,
    ffi::{OsStr, OsString},
    fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use deno_config::deno_json::NodeModulesDirMode;
use deno_core::{
    anyhow::{Context, anyhow},
    error::AnyError,
    serde_json::Value,
};
use deno_error::JsErrorBox;
use deno_npm_cache::{
    DownloadError, NpmCacheHttpClient, NpmCacheHttpClientBytesResponse, NpmCacheHttpClientResponse,
    NpmCacheSetting, NpmPackumentFormat,
};
use deno_npm_installer::{
    LifecycleScriptsConfig, LogReporter, NpmInstallerFactory, NpmInstallerFactoryOptions,
    PackageCaching, PackagesAllowedScripts,
    graph::NpmCachingStrategy,
    lifecycle_scripts::{
        LIFECYCLE_SCRIPTS_RUNNING_ENV_VAR, LifecycleScriptsExecutor,
        LifecycleScriptsExecutorOptions, NullLifecycleScriptsExecutor, PackageWithScript,
        compute_lifecycle_script_layers,
    },
};
use deno_npmrc::RegistryConfig;
use deno_resolver::factory::{
    ConfigDiscoveryOption, ResolverFactory, ResolverFactoryOptions, WorkspaceFactory,
    WorkspaceFactoryOptions,
};
use deno_task_shell::{KillSignal, ShellPipeReader, ShellState, execute_with_pipes, parser};
use http::header;
use sys_traits::impls::RealSys;
use tokio::task::{JoinHandle, LocalSet};
use url::Url;

const NPM_CACHE_RETRY_DELAY: Duration = Duration::from_millis(250);
const NPM_CACHE_RETRY_COUNT: usize = 3;
const NPM_PACKUMENT_ACCEPT_HEADER: &str =
    "application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8, */*";

#[derive(Clone, Debug)]
pub(crate) struct RuntimeNpm {
    package_json_path: PathBuf,
}

#[derive(Debug)]
pub(crate) struct RuntimeNpmError(String);

#[derive(Clone, Copy)]
enum RuntimeNpmOperation {
    Lock,
    Sync,
}

type RuntimeNpmInstallerFactory =
    NpmInstallerFactory<ReqwestNpmCacheHttpClient, LogReporter, RealSys>;

#[derive(Clone, Debug, Default)]
struct RuntimeLifecycleScriptsExecutor;

struct RuntimeShellTaskResult {
    exit_code: i32,
    stderr: Vec<u8>,
    stdout: Vec<u8>,
}

struct RuntimeLinkedLifecyclePackage {
    name: String,
    package_folder: PathBuf,
    scripts: HashMap<String, String>,
    version: String,
}

impl RuntimeNpm {
    pub(crate) fn new(package_json_path: PathBuf) -> Self {
        Self { package_json_path }
    }

    pub(crate) fn lock(&self) -> Result<(), RuntimeNpmError> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|err| {
                RuntimeNpmError::new(format!("Failed to create Tokio runtime: {err}"))
            })?;
        runtime.block_on(self.run(RuntimeNpmOperation::Lock))
    }

    pub(crate) fn sync(&self) -> Result<(), RuntimeNpmError> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|err| {
                RuntimeNpmError::new(format!("Failed to create Tokio runtime: {err}"))
            })?;
        runtime.block_on(self.run(RuntimeNpmOperation::Sync))
    }

    async fn run(&self, operation: RuntimeNpmOperation) -> Result<(), RuntimeNpmError> {
        node_resolver::PackageJsonThreadLocalCache::clear();

        let package_json_dir = self.package_json_dir()?;
        let npm_installer_factory = self.npm_installer_factory(
            &package_json_dir,
            matches!(operation, RuntimeNpmOperation::Sync),
        )?;
        let npm_installer = npm_installer_factory.npm_installer().await.map_err(|err| {
            RuntimeNpmError::new(format!("Failed to prepare npm installer: {err}"))
        })?;

        npm_installer
            .ensure_no_pkg_json_dep_errors()
            .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
        npm_installer
            .ensure_top_level_package_json_install()
            .await
            .map_err(|err| RuntimeNpmError::new(err.to_string()))?;

        match operation {
            RuntimeNpmOperation::Lock => {
                npm_installer
                    .install_resolution_if_pending()
                    .await
                    .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
            }
            RuntimeNpmOperation::Sync => {
                npm_installer
                    .cache_packages(PackageCaching::All)
                    .await
                    .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
                self.run_linked_lifecycle_scripts(&package_json_dir).await?;
            }
        }

        if let Some(lockfile) = npm_installer_factory
            .maybe_lockfile()
            .await
            .map_err(|err| RuntimeNpmError::new(format!("Failed to resolve lockfile: {err}")))?
        {
            lockfile
                .write_if_changed()
                .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
        }

        Ok(())
    }

    fn package_json_dir(&self) -> Result<PathBuf, RuntimeNpmError> {
        self.package_json_path
            .parent()
            .map(Path::to_path_buf)
            .ok_or_else(|| {
                RuntimeNpmError::new(format!(
                    "package_json path '{}' has no parent directory",
                    self.package_json_path.display()
                ))
            })
    }

    fn npm_installer_factory(
        &self,
        package_json_dir: &Path,
        clean_on_install: bool,
    ) -> Result<RuntimeNpmInstallerFactory, RuntimeNpmError> {
        let sys = RealSys;
        let workspace_factory = Arc::new(WorkspaceFactory::new(
            sys,
            package_json_dir.to_path_buf(),
            WorkspaceFactoryOptions {
                config_discovery: ConfigDiscoveryOption::Discover {
                    start_paths: vec![package_json_dir.to_path_buf()],
                },
                is_package_manager_subcommand: true,
                lock_arg: Some(package_json_dir.join("deno.lock")),
                node_modules_dir: Some(NodeModulesDirMode::Auto),
                ..Default::default()
            },
        ));
        let resolver_factory = Arc::new(ResolverFactory::new(
            workspace_factory,
            ResolverFactoryOptions {
                package_json_cache: Some(Arc::new(node_resolver::PackageJsonThreadLocalCache)),
                ..Default::default()
            },
        ));
        let packument_format = if resolver_factory
            .minimum_dependency_age_config()
            .map_err(|err| {
                RuntimeNpmError::new(format!("Failed to read minimumDependencyAge: {err}"))
            })?
            .age
            .is_some()
        {
            NpmPackumentFormat::Full
        } else {
            NpmPackumentFormat::Abbreviated
        };
        let package_json_dir = package_json_dir.to_path_buf();
        let lifecycle_scripts_executor: Arc<dyn LifecycleScriptsExecutor> = if clean_on_install {
            Arc::new(RuntimeLifecycleScriptsExecutor)
        } else {
            Arc::new(NullLifecycleScriptsExecutor)
        };

        Ok(NpmInstallerFactory::new(
            resolver_factory,
            Arc::new(ReqwestNpmCacheHttpClient::new(packument_format)?),
            lifecycle_scripts_executor,
            LogReporter,
            None,
            NpmInstallerFactoryOptions {
                cache_setting: NpmCacheSetting::Use,
                caching_strategy: NpmCachingStrategy::Manual,
                clean_on_install,
                lifecycle_scripts_config: LifecycleScriptsConfig {
                    allowed: if clean_on_install {
                        PackagesAllowedScripts::All
                    } else {
                        PackagesAllowedScripts::None
                    },
                    initial_cwd: package_json_dir.clone(),
                    root_dir: package_json_dir,
                    explicit_install: true,
                    ..Default::default()
                },
                resolve_npm_resolution_snapshot: Box::new(|| Ok(None)),
            },
        ))
    }

    async fn run_linked_lifecycle_scripts(
        &self,
        package_json_dir: &Path,
    ) -> Result<(), RuntimeNpmError> {
        let root_node_modules_dir = package_json_dir.join("node_modules");

        for package in linked_lifecycle_packages(package_json_dir)? {
            let base_env_vars = lifecycle_base_env_vars(
                &package.name,
                &package.version,
                &package.package_folder,
                package_json_dir,
                &root_node_modules_dir,
            );

            for script_name in ["preinstall", "install", "postinstall"] {
                let Some(script) = package.scripts.get(script_name) else {
                    continue;
                };
                let mut env_vars = base_env_vars.clone();
                env_vars.insert("npm_lifecycle_event".into(), script_name.into());
                env_vars.insert("npm_lifecycle_script".into(), script.into());

                let result = run_shell_task(
                    script_name,
                    script,
                    package.package_folder.clone(),
                    env_vars,
                )
                .await
                .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
                if result.exit_code != 0 {
                    return Err(RuntimeNpmError::new(format!(
                        "lifecycle script '{}' failed for '{}' with exit code {}{}{}",
                        script_name,
                        package.name,
                        result.exit_code,
                        format_task_output("stdout", &result.stdout),
                        format_task_output("stderr", &result.stderr),
                    )));
                }
            }
        }

        Ok(())
    }
}

#[async_trait::async_trait(?Send)]
impl LifecycleScriptsExecutor for RuntimeLifecycleScriptsExecutor {
    async fn execute(&self, options: LifecycleScriptsExecutorOptions<'_>) -> Result<(), AnyError> {
        for layer in
            compute_lifecycle_script_layers(options.packages_with_scripts, options.snapshot)
        {
            for package in layer {
                self.run_package_scripts(package, &options).await?;
                (options.on_ran_pkg_scripts)(package.package)?;
            }
        }

        Ok(())
    }
}

impl RuntimeLifecycleScriptsExecutor {
    async fn run_package_scripts(
        &self,
        package: &PackageWithScript<'_>,
        options: &LifecycleScriptsExecutorOptions<'_>,
    ) -> Result<(), AnyError> {
        let base_env_vars = self.base_env_vars(package, options);

        for script_name in ["preinstall", "install", "postinstall"] {
            let Some(script) = package.scripts.get(script_name) else {
                continue;
            };
            let mut env_vars = base_env_vars.clone();
            env_vars.insert("npm_lifecycle_event".into(), script_name.into());
            env_vars.insert("npm_lifecycle_script".into(), script.into());

            let result = run_shell_task(
                script_name,
                script,
                package.package_folder.clone(),
                env_vars,
            )
            .await?;
            if result.exit_code != 0 {
                return Err(anyhow!(
                    "lifecycle script '{}' failed for '{}' with exit code {}{}{}",
                    script_name,
                    package.package.id.nv,
                    result.exit_code,
                    format_task_output("stdout", &result.stdout),
                    format_task_output("stderr", &result.stderr),
                ));
            }
        }

        Ok(())
    }

    fn base_env_vars(
        &self,
        package: &PackageWithScript<'_>,
        options: &LifecycleScriptsExecutorOptions<'_>,
    ) -> HashMap<OsString, OsString> {
        lifecycle_base_env_vars(
            &package.package.id.nv.name.to_string(),
            &package.package.id.nv.version.to_string(),
            &package.package_folder,
            options.init_cwd,
            options.root_node_modules_dir_path,
        )
    }
}

impl RuntimeNpmError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl std::fmt::Display for RuntimeNpmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}

impl std::error::Error for RuntimeNpmError {}

#[derive(Clone, Debug)]
struct ReqwestNpmCacheHttpClient {
    client: reqwest::Client,
    packument_format: NpmPackumentFormat,
}

impl ReqwestNpmCacheHttpClient {
    fn new(packument_format: NpmPackumentFormat) -> Result<Self, RuntimeNpmError> {
        let client = reqwest::Client::builder()
            .user_agent(format!("gdansk-runtime/{}", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|err| {
                RuntimeNpmError::new(format!("Failed to create npm HTTP client: {err}"))
            })?;

        Ok(Self {
            client,
            packument_format,
        })
    }

    fn request(
        &self,
        url: Url,
        maybe_auth: Option<&str>,
        maybe_etag: Option<&str>,
    ) -> reqwest::RequestBuilder {
        let mut request = self.client.get(url);
        if let Some(auth) = maybe_auth {
            request = request.header(header::AUTHORIZATION, auth);
        }
        if let Some(etag) = maybe_etag {
            request = request.header(header::IF_NONE_MATCH, etag);
        }
        if self.packument_format == NpmPackumentFormat::Abbreviated {
            request = request.header(header::ACCEPT, NPM_PACKUMENT_ACCEPT_HEADER);
        }
        request
    }
}

#[async_trait::async_trait(?Send)]
impl NpmCacheHttpClient for ReqwestNpmCacheHttpClient {
    async fn download_with_retries_on_any_tokio_runtime(
        &self,
        url: Url,
        maybe_auth: Option<String>,
        maybe_etag: Option<String>,
        _maybe_registry_config: Option<&RegistryConfig>,
    ) -> Result<NpmCacheHttpClientResponse, DownloadError> {
        let maybe_auth = maybe_auth.as_deref();
        let maybe_etag = maybe_etag.as_deref();
        let mut last_error = None;

        for attempt in 0..NPM_CACHE_RETRY_COUNT {
            match self
                .request(url.clone(), maybe_auth, maybe_etag)
                .send()
                .await
            {
                Ok(response) => {
                    let status = response.status();
                    if status == reqwest::StatusCode::NOT_FOUND {
                        return Ok(NpmCacheHttpClientResponse::NotFound);
                    }
                    if status == reqwest::StatusCode::NOT_MODIFIED {
                        return Ok(NpmCacheHttpClientResponse::NotModified);
                    }
                    if status.is_success() {
                        let etag = response
                            .headers()
                            .get(header::ETAG)
                            .and_then(|value| value.to_str().ok())
                            .map(ToOwned::to_owned);
                        let bytes = response
                            .bytes()
                            .await
                            .map_err(|err| download_error(None, err.to_string()))?;
                        return Ok(NpmCacheHttpClientResponse::Bytes(
                            NpmCacheHttpClientBytesResponse {
                                bytes: bytes.to_vec(),
                                etag,
                            },
                        ));
                    }

                    let error = download_error(
                        Some(status.as_u16()),
                        format!("Failed to download '{url}': {status}"),
                    );
                    if status.is_server_error() && attempt + 1 < NPM_CACHE_RETRY_COUNT {
                        last_error = Some(error);
                        tokio::time::sleep(NPM_CACHE_RETRY_DELAY).await;
                        continue;
                    }
                    return Err(error);
                }
                Err(err) => {
                    let error = download_error(None, format!("Failed to download '{url}': {err}"));
                    if attempt + 1 < NPM_CACHE_RETRY_COUNT {
                        last_error = Some(error);
                        tokio::time::sleep(NPM_CACHE_RETRY_DELAY).await;
                        continue;
                    }
                    return Err(error);
                }
            }
        }

        Err(last_error
            .unwrap_or_else(|| download_error(None, format!("Failed to download '{url}'"))))
    }
}

fn download_error(status_code: Option<u16>, message: impl Into<String>) -> DownloadError {
    DownloadError {
        status_code,
        error: JsErrorBox::generic(message.into()),
    }
}

fn lifecycle_script_path_entries(
    package_folder: &Path,
    root_node_modules_dir_path: &Path,
) -> Vec<PathBuf> {
    let mut paths = vec![package_folder.join("node_modules").join(".bin")];

    for ancestor in package_folder.ancestors() {
        if ancestor.file_name() == Some(OsStr::new("node_modules")) {
            let candidate = ancestor.join(".bin");
            if !paths.contains(&candidate) {
                paths.push(candidate);
            }
        }
        if ancestor == root_node_modules_dir_path {
            break;
        }
    }

    let root_bin = root_node_modules_dir_path.join(".bin");
    if !paths.contains(&root_bin) {
        paths.push(root_bin);
    }

    paths
}

fn lifecycle_base_env_vars(
    package_name: &str,
    package_version: &str,
    package_folder: &Path,
    init_cwd: &Path,
    root_node_modules_dir_path: &Path,
) -> HashMap<OsString, OsString> {
    let mut env_vars = std::env::vars_os().collect::<HashMap<_, _>>();
    env_vars.insert("INIT_CWD".into(), init_cwd.as_os_str().into());
    env_vars.insert(LIFECYCLE_SCRIPTS_RUNNING_ENV_VAR.into(), "1".into());
    env_vars.insert(
        "npm_config_user_agent".into(),
        format!("gdansk-runtime/{}", env!("CARGO_PKG_VERSION")).into(),
    );
    env_vars.insert("npm_execpath".into(), "gdansk-runtime".into());
    env_vars.insert(
        "npm_package_json".into(),
        package_folder.join("package.json").into_os_string(),
    );
    env_vars.insert("npm_package_name".into(), package_name.into());
    env_vars.insert("npm_package_version".into(), package_version.into());
    prepend_to_path(
        &mut env_vars,
        lifecycle_script_path_entries(package_folder, root_node_modules_dir_path),
    );
    env_vars
}

fn linked_lifecycle_packages(
    package_json_dir: &Path,
) -> Result<Vec<RuntimeLinkedLifecyclePackage>, RuntimeNpmError> {
    let root_package_json = fs::read_to_string(package_json_dir.join("package.json"))
        .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
    let root_package_json = deno_core::serde_json::from_str::<Value>(&root_package_json)
        .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
    let mut packages = Vec::new();

    for dependencies_key in [
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ] {
        let Some(dependencies) = root_package_json
            .get(dependencies_key)
            .and_then(Value::as_object)
        else {
            continue;
        };

        for dependency_specifier in dependencies.values() {
            let Some(dependency_specifier) = dependency_specifier.as_str() else {
                continue;
            };
            let Some(path_specifier) = dependency_specifier.strip_prefix("file:") else {
                continue;
            };
            let package_folder = package_json_dir.join(path_specifier);
            let package = linked_lifecycle_package(&package_folder)?;
            if let Some(package) = package
                && !packages
                    .iter()
                    .any(|candidate: &RuntimeLinkedLifecyclePackage| {
                        candidate.package_folder == package.package_folder
                    })
            {
                packages.push(package);
            }
        }
    }

    Ok(packages)
}

fn linked_lifecycle_package(
    package_folder: &Path,
) -> Result<Option<RuntimeLinkedLifecyclePackage>, RuntimeNpmError> {
    let package_json = fs::read_to_string(package_folder.join("package.json"))
        .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
    let package_json = deno_core::serde_json::from_str::<Value>(&package_json)
        .map_err(|err| RuntimeNpmError::new(err.to_string()))?;
    let Some(scripts) = package_json.get("scripts").and_then(Value::as_object) else {
        return Ok(None);
    };

    let scripts = scripts
        .iter()
        .filter_map(|(name, value)| match value.as_str() {
            Some(value) if matches!(name.as_str(), "preinstall" | "install" | "postinstall") => {
                Some((name.clone(), value.to_owned()))
            }
            _ => None,
        })
        .collect::<HashMap<_, _>>();
    if scripts.is_empty() {
        return Ok(None);
    }

    let name = package_json
        .get("name")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| package_folder.display().to_string());
    let version = package_json
        .get("version")
        .and_then(Value::as_str)
        .unwrap_or("0.0.0")
        .to_owned();

    Ok(Some(RuntimeLinkedLifecyclePackage {
        name,
        package_folder: package_folder.to_path_buf(),
        scripts,
        version,
    }))
}

fn prepend_to_path(
    env_vars: &mut HashMap<OsString, OsString>,
    values: impl IntoIterator<Item = PathBuf>,
) {
    let separator = if cfg!(windows) { ";" } else { ":" };
    let new_path = values
        .into_iter()
        .map(PathBuf::into_os_string)
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>();

    if new_path.is_empty() {
        return;
    }

    let mut joined = OsString::new();
    for (index, value) in new_path.into_iter().enumerate() {
        if index > 0 {
            joined.push(separator);
        }
        joined.push(value);
    }

    match env_vars.get_mut(OsStr::new("PATH")) {
        Some(path) if !path.is_empty() => {
            joined.push(separator);
            joined.push(path.as_os_str());
            *path = joined;
        }
        Some(path) => {
            *path = joined;
        }
        None => {
            env_vars.insert("PATH".into(), joined);
        }
    }
}

fn read_pipe(reader: ShellPipeReader) -> JoinHandle<Result<Vec<u8>, AnyError>> {
    tokio::task::spawn_blocking(move || {
        let mut buffer = Vec::new();
        reader.pipe_to(&mut buffer)?;
        Ok(buffer)
    })
}

async fn run_shell_task(
    task_name: &str,
    script: &str,
    cwd: PathBuf,
    env_vars: HashMap<OsString, OsString>,
) -> Result<RuntimeShellTaskResult, AnyError> {
    let parsed = parser::parse(script)
        .with_context(|| format!("failed to parse lifecycle script '{task_name}'"))?;
    let state = ShellState::new(env_vars, cwd, HashMap::new(), KillSignal::default());
    let (stdout_reader, stdout_writer) = deno_task_shell::pipe();
    let (stderr_reader, stderr_writer) = deno_task_shell::pipe();
    let stdout = read_pipe(stdout_reader);
    let stderr = read_pipe(stderr_reader);
    let local = LocalSet::new();

    local
        .run_until(async move {
            let exit_code = execute_with_pipes(
                parsed,
                state,
                ShellPipeReader::stdin(),
                stdout_writer,
                stderr_writer,
            )
            .await;
            Ok(RuntimeShellTaskResult {
                exit_code,
                stderr: stderr.await??,
                stdout: stdout.await??,
            })
        })
        .await
}

fn format_task_output(label: &str, bytes: &[u8]) -> String {
    let output = String::from_utf8_lossy(bytes);
    let trimmed = output.trim();
    if trimmed.is_empty() {
        String::new()
    } else {
        format!("\n{label}:\n{trimmed}")
    }
}
