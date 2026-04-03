use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use deno_config::deno_json::NodeModulesDirMode;
use deno_error::JsErrorBox;
use deno_npm_cache::{
    DownloadError, NpmCacheHttpClient, NpmCacheHttpClientBytesResponse, NpmCacheHttpClientResponse,
    NpmCacheSetting, NpmPackumentFormat,
};
use deno_npm_installer::{
    LifecycleScriptsConfig, LogReporter, NpmInstallerFactory, NpmInstallerFactoryOptions,
    PackageCaching, graph::NpmCachingStrategy, lifecycle_scripts::NullLifecycleScriptsExecutor,
};
use deno_npmrc::RegistryConfig;
use deno_resolver::factory::{
    ConfigDiscoveryOption, ResolverFactory, ResolverFactoryOptions, WorkspaceFactory,
    WorkspaceFactoryOptions,
};
use http::header;
use sys_traits::impls::RealSys;
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
        let sys = RealSys::default();
        let workspace_factory = Arc::new(WorkspaceFactory::new(
            sys,
            package_json_dir.to_path_buf(),
            WorkspaceFactoryOptions {
                config_discovery: ConfigDiscoveryOption::Path(self.package_json_path.clone()),
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

        Ok(NpmInstallerFactory::new(
            resolver_factory,
            Arc::new(ReqwestNpmCacheHttpClient::new(packument_format)?),
            Arc::new(NullLifecycleScriptsExecutor),
            LogReporter,
            None,
            NpmInstallerFactoryOptions {
                cache_setting: NpmCacheSetting::Use,
                caching_strategy: NpmCachingStrategy::Manual,
                clean_on_install,
                lifecycle_scripts_config: LifecycleScriptsConfig {
                    initial_cwd: package_json_dir.clone(),
                    root_dir: package_json_dir,
                    explicit_install: true,
                    ..Default::default()
                },
                production: false,
                skip_types: false,
                resolve_npm_resolution_snapshot: Box::new(|| Ok(None)),
            },
        ))
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
