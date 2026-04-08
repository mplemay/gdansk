use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    sync::Arc,
};

use rolldown::{Bundler as RolldownBundler, BundlerOptions, InputItem};
use rolldown_common::ScanMode;
use rolldown_fs_watcher::{
    DynFsWatcher, FsEventHandler, FsEventResult, FsWatcherConfig, RecursiveMode, create_fs_watcher,
};
use tokio::sync::{Mutex, mpsc, oneshot};
use tokio::time::{Duration, Instant};

use crate::{
    BundlerConfigState, BundlerOutput, OutputConfig, create_bundler_options, format_diagnostics,
};

fn normalize_watch_string(raw: &str) -> String {
    let path = Path::new(raw);
    let Ok(exists) = path.try_exists() else {
        return raw.to_owned();
    };
    if !exists {
        return raw.to_owned();
    }
    dunce::canonicalize(path)
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| raw.to_owned())
}

enum WatchCommand {
    SetWatchFiles {
        paths: Vec<PathBuf>,
        reply: oneshot::Sender<Result<(), String>>,
    },
    Close {
        reply: oneshot::Sender<Result<(), String>>,
    },
}

struct WatchEventHandler {
    tx: mpsc::UnboundedSender<FsEventResult>,
}

impl FsEventHandler for WatchEventHandler {
    fn handle_event(&mut self, event: FsEventResult) {
        let _ = self.tx.send(event);
    }
}

struct WatchSessionInner {
    command_tx: mpsc::UnboundedSender<WatchCommand>,
    rebuild_rx: Mutex<mpsc::UnboundedReceiver<Result<BundlerOutput, String>>>,
}

#[derive(Clone)]
pub(crate) struct WatchSession {
    inner: Arc<WatchSessionInner>,
}

impl WatchSession {
    pub(crate) async fn start(
        config: Arc<BundlerConfigState>,
        input: Vec<InputItem>,
        output_override: Option<OutputConfig>,
        write: Option<bool>,
        watch_files: Vec<PathBuf>,
    ) -> Result<(Self, BundlerOutput), String> {
        let (options, should_write) =
            create_bundler_options(config.as_ref(), input, output_override, write, true)
                .map_err(|err| err.to_string())?;
        let (command_tx, command_rx) = mpsc::unbounded_channel();
        let (rebuild_tx, rebuild_rx) = mpsc::unbounded_channel();
        let (initial_tx, initial_rx) = oneshot::channel();

        tokio::spawn(run_watch_task(
            options,
            config.plugins.clone(),
            should_write,
            watch_files,
            command_rx,
            rebuild_tx,
            initial_tx,
        ));

        let initial = initial_rx.await.map_err(|_| {
            "watch session terminated before the initial build completed".to_owned()
        })??;

        Ok((
            Self {
                inner: Arc::new(WatchSessionInner {
                    command_tx,
                    rebuild_rx: Mutex::new(rebuild_rx),
                }),
            },
            initial,
        ))
    }

    pub(crate) async fn wait_for_rebuild(&self) -> Result<BundlerOutput, String> {
        let mut rebuild_rx = self.inner.rebuild_rx.lock().await;
        rebuild_rx.recv().await.ok_or_else(|| {
            "watch session terminated before a rebuild result was available".to_owned()
        })?
    }

    pub(crate) async fn set_watch_files(&self, paths: Vec<PathBuf>) -> Result<(), String> {
        let (reply_tx, reply_rx) = oneshot::channel();
        self.inner
            .command_tx
            .send(WatchCommand::SetWatchFiles {
                paths,
                reply: reply_tx,
            })
            .map_err(|_| "watch session is no longer running".to_owned())?;
        reply_rx
            .await
            .map_err(|_| "watch session terminated before updating watch files".to_owned())?
    }

    pub(crate) async fn close(&self) -> Result<(), String> {
        let (reply_tx, reply_rx) = oneshot::channel();
        self.inner
            .command_tx
            .send(WatchCommand::Close { reply: reply_tx })
            .map_err(|_| "watch session is no longer running".to_owned())?;
        reply_rx
            .await
            .map_err(|_| "watch session terminated before closing".to_owned())?
    }
}

async fn run_watch_task(
    options: BundlerOptions,
    plugins: Vec<rolldown_plugin::__inner::SharedPluginable>,
    should_write: bool,
    initial_watch_files: Vec<PathBuf>,
    mut command_rx: mpsc::UnboundedReceiver<WatchCommand>,
    rebuild_tx: mpsc::UnboundedSender<Result<BundlerOutput, String>>,
    initial_tx: oneshot::Sender<Result<BundlerOutput, String>>,
) {
    const FAILED_REBUILD_RETRY_DELAY: Duration = Duration::from_millis(100);
    const REBUILD_SETTLE_DELAY: Duration = Duration::from_millis(25);
    /// Upper bound on coalesced `run_full_build` loops per FS notification. Without this, a stream
    /// of spurious post-build events (e.g. writes under watched paths) can keep
    /// `drain_rebuild_triggers` true forever so `handle_rebuild_result` never runs and consumers
    /// like `wait_for_rebuild()` stall.
    const MAX_FS_COALESCE_BUILDS: usize = 16;

    let mut bundler = match RolldownBundler::with_plugins(options, plugins) {
        Ok(bundler) => bundler,
        Err(errs) => {
            let _ = initial_tx.send(Err(format_diagnostics(
                "failed to initialize Bundler",
                &errs,
            )));
            return;
        }
    };

    let (fs_event_tx, mut fs_event_rx) = mpsc::unbounded_channel();
    let event_handler = WatchEventHandler { tx: fs_event_tx };
    let mut watcher = match create_fs_watcher(event_handler, FsWatcherConfig::default()) {
        Ok(watcher) => watcher,
        Err(err) => {
            let _ = initial_tx.send(Err(format!("failed to create file watcher: {err}")));
            let _ = close_bundler(&mut bundler).await;
            return;
        }
    };

    let mut is_initial_build = true;
    let mut current_watch_files = BTreeSet::new();
    let mut extra_watch_files = initial_watch_files.into_iter().collect::<BTreeSet<_>>();
    let mut retry_due_at: Option<Instant> = None;
    let mut last_reported_error: Option<String> = None;

    match run_full_build(
        &mut bundler,
        &mut watcher,
        &mut current_watch_files,
        &extra_watch_files,
        should_write,
        &mut is_initial_build,
    )
    .await
    {
        Ok(output) => {
            let _ = initial_tx.send(Ok(output));
        }
        Err(err) => {
            let _ = initial_tx.send(Err(err));
            let _ = close_bundler(&mut bundler).await;
            return;
        }
    }

    loop {
        tokio::select! {
            _ = tokio::time::sleep_until(
                retry_due_at.unwrap_or_else(|| Instant::now() + FAILED_REBUILD_RETRY_DELAY)
            ), if retry_due_at.is_some() => {
                handle_rebuild_result(
                    run_full_build(
                        &mut bundler,
                        &mut watcher,
                        &mut current_watch_files,
                        &extra_watch_files,
                        should_write,
                        &mut is_initial_build,
                    )
                    .await,
                    &rebuild_tx,
                    &mut retry_due_at,
                    &mut last_reported_error,
                    FAILED_REBUILD_RETRY_DELAY,
                );
            }
            command = command_rx.recv() => {
                let Some(command) = command else {
                    break;
                };
                match command {
                    WatchCommand::SetWatchFiles { paths, reply } => {
                        extra_watch_files = paths.into_iter().collect();
                        let result = sync_watch_files(
                            &mut watcher,
                            &mut current_watch_files,
                            collect_watch_files(&bundler, &extra_watch_files),
                        );
                        let _ = reply.send(result);
                    }
                    WatchCommand::Close { reply } => {
                        let result = close_bundler(&mut bundler).await;
                        let _ = reply.send(result);
                        return;
                    }
                }
            }
            event = fs_event_rx.recv() => {
                let Some(event) = event else {
                    break;
                };
                if !has_rebuild_trigger(event) {
                    continue;
                }
                let mut coalesce_builds: usize = 0;
                loop {
                    // Native file watchers can emit multiple events for a single save. Wait for
                    // a short quiet period so we return the settled rebuild output instead of an
                    // intermediate result from the first metadata event.
                    wait_for_fs_events_to_settle(&mut fs_event_rx, REBUILD_SETTLE_DELAY).await;
                    let result = run_full_build(
                        &mut bundler,
                        &mut watcher,
                        &mut current_watch_files,
                        &extra_watch_files,
                        should_write,
                        &mut is_initial_build,
                    )
                    .await;
                    coalesce_builds += 1;
                    let saw_more_triggers = drain_rebuild_triggers(&mut fs_event_rx);
                    if saw_more_triggers && coalesce_builds < MAX_FS_COALESCE_BUILDS {
                        continue;
                    }
                    handle_rebuild_result(
                        result,
                        &rebuild_tx,
                        &mut retry_due_at,
                        &mut last_reported_error,
                        FAILED_REBUILD_RETRY_DELAY,
                    );
                    break;
                }
            }
        }
    }

    let _ = close_bundler(&mut bundler).await;
}

fn handle_rebuild_result(
    result: Result<BundlerOutput, String>,
    rebuild_tx: &mpsc::UnboundedSender<Result<BundlerOutput, String>>,
    retry_due_at: &mut Option<Instant>,
    last_reported_error: &mut Option<String>,
    retry_delay: Duration,
) {
    match result {
        Ok(output) => {
            *retry_due_at = None;
            *last_reported_error = None;
            let _ = rebuild_tx.send(Ok(output));
        }
        Err(err) => {
            *retry_due_at = Some(Instant::now() + retry_delay);
            if last_reported_error.as_ref() == Some(&err) {
                return;
            }
            *last_reported_error = Some(err.clone());
            let _ = rebuild_tx.send(Err(err));
        }
    }
}

async fn run_full_build(
    bundler: &mut RolldownBundler,
    watcher: &mut DynFsWatcher,
    current_watch_files: &mut BTreeSet<String>,
    extra_watch_files: &BTreeSet<PathBuf>,
    should_write: bool,
    is_initial_build: &mut bool,
) -> Result<BundlerOutput, String> {
    bundler.clear_resolver_cache();
    let bundle_output = if *is_initial_build {
        *is_initial_build = false;
        if should_write {
            bundler.write().await
        } else {
            bundler.generate().await
        }
    } else if should_write {
        bundler.incremental_write(ScanMode::Full).await
    } else {
        bundler.incremental_generate(ScanMode::Full).await
    }
    .map_err(|errs| format_diagnostics("bundling failed", &errs))?;

    sync_watch_files(
        watcher,
        current_watch_files,
        collect_watch_files(bundler, extra_watch_files),
    )?;

    Ok(BundlerOutput::from_bundle_output(bundle_output))
}

fn collect_watch_files(
    bundler: &RolldownBundler,
    extra_watch_files: &BTreeSet<PathBuf>,
) -> BTreeSet<String> {
    let mut watch_files = bundler
        .watch_files()
        .iter()
        .map(|path| normalize_watch_string(&path.to_string()))
        .collect::<BTreeSet<_>>();
    watch_files.extend(
        extra_watch_files
            .iter()
            .map(|path| normalize_watch_string(path.to_string_lossy().as_ref())),
    );
    watch_files
}

fn sync_watch_files(
    watcher: &mut DynFsWatcher,
    current_watch_files: &mut BTreeSet<String>,
    desired_watch_files: BTreeSet<String>,
) -> Result<(), String> {
    let stale_watch_files = current_watch_files
        .difference(&desired_watch_files)
        .cloned()
        .collect::<Vec<_>>();
    let new_watch_files = desired_watch_files
        .difference(current_watch_files)
        .cloned()
        .collect::<Vec<_>>();

    let mut paths_mut = watcher.paths_mut();

    for stale_watch_file in stale_watch_files {
        let path = Path::new(&stale_watch_file);
        let remove_target = if path.try_exists().unwrap_or(false) {
            dunce::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
        } else {
            path.to_path_buf()
        };
        let _ = paths_mut.remove(remove_target.as_path());
    }

    for new_watch_file in new_watch_files {
        let path = Path::new(&new_watch_file);
        if !path.try_exists().unwrap_or(false) {
            continue;
        }
        let resolved = dunce::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
        let _ = paths_mut.add(resolved.as_path(), RecursiveMode::NonRecursive);
    }

    paths_mut
        .commit()
        .map_err(|err| format!("failed to update file watcher paths: {err}"))?;
    *current_watch_files = desired_watch_files;
    Ok(())
}

fn has_rebuild_trigger(event: FsEventResult) -> bool {
    match event {
        Ok(events) => events.into_iter().any(|event| {
            matches!(
                event.detail.kind,
                notify::EventKind::Create(_)
                    | notify::EventKind::Modify(_)
                    | notify::EventKind::Remove(_)
            )
        }),
        Err(errs) => {
            eprintln!("gdansk_bundler watch error: {errs:?}");
            false
        }
    }
}

fn drain_rebuild_triggers(fs_event_rx: &mut mpsc::UnboundedReceiver<FsEventResult>) -> bool {
    let mut saw_rebuild_trigger = false;

    while let Ok(event) = fs_event_rx.try_recv() {
        saw_rebuild_trigger |= has_rebuild_trigger(event);
    }

    saw_rebuild_trigger
}

async fn wait_for_fs_events_to_settle(
    fs_event_rx: &mut mpsc::UnboundedReceiver<FsEventResult>,
    delay: Duration,
) {
    loop {
        tokio::time::sleep(delay).await;
        if !drain_rebuild_triggers(fs_event_rx) {
            return;
        }
    }
}

async fn close_bundler(bundler: &mut RolldownBundler) -> Result<(), String> {
    bundler
        .close()
        .await
        .map_err(|errs| format_diagnostics("failed to close Bundler", &errs))
}
