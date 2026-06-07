use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};

use deno_core::anyhow::{Context, bail};
use deno_core::error::AnyError;

use crate::packages::PackageEnvironment;
use crate::task::deno_exe::resolve_deno_exe;
use crate::task::types::{RunTaskOptions, TaskResult};

#[derive(Debug)]
pub(crate) struct TaskProcess {
    inner: Arc<TaskProcessInner>,
}

#[derive(Debug)]
struct TaskProcessInner {
    origin: String,
    child: Mutex<Option<Child>>,
}

impl TaskProcess {
    pub(crate) fn origin(&self) -> &str {
        &self.inner.origin
    }

    pub(crate) fn stop_blocking(&self) -> Result<(), AnyError> {
        let mut guard = self
            .inner
            .child
            .lock()
            .expect("task process child lock should not be poisoned");
        let Some(mut child) = guard.take() else {
            return Ok(());
        };
        terminate_child(&mut child)?;
        child
            .wait()
            .context("Failed to wait for task subprocess after stop")?;
        Ok(())
    }
}

impl Drop for TaskProcess {
    fn drop(&mut self) {
        let _ = self.stop_blocking();
    }
}

#[derive(Debug, Default)]
pub(crate) struct TaskRunner;

impl TaskRunner {
    pub(crate) fn run_blocking(&self, options: RunTaskOptions) -> Result<TaskResult, AnyError> {
        let status = spawn_deno_task(&options, false)?
            .wait()
            .context("Failed to wait for task subprocess")?;
        Ok(TaskResult {
            exit_code: status.code().unwrap_or(1),
        })
    }

    pub(crate) fn start_blocking(&self, options: RunTaskOptions) -> Result<TaskProcess, AnyError> {
        let origin = task_origin(&options)?;
        let child = spawn_deno_task(&options, true)?;
        Ok(TaskProcess {
            inner: Arc::new(TaskProcessInner {
                origin,
                child: Mutex::new(Some(child)),
            }),
        })
    }
}

fn task_origin(options: &RunTaskOptions) -> Result<String, AnyError> {
    if let (Some(host), Some(port)) = (&options.host, options.port) {
        return Ok(format!("http://{host}:{port}"));
    }
    bail!("Long-running tasks require both host and port in task options")
}

fn spawn_deno_task(options: &RunTaskOptions, background: bool) -> Result<Child, AnyError> {
    let env = PackageEnvironment::for_task(&options.task_cwd, &options.script)?;
    let pyproject_dir = env.cwd().to_path_buf();
    let deno_exe = resolve_deno_exe()?;
    let task_cwd = options
        .task_cwd
        .canonicalize()
        .unwrap_or_else(|_| options.task_cwd.clone());

    let mut command = Command::new(deno_exe);
    command
        .arg("--config")
        .arg(env.config_file())
        .arg("--lock")
        .arg(env.lockfile())
        .arg("task")
        .arg("--cwd")
        .arg(&task_cwd)
        .arg(&options.script)
        .arg("--")
        .args(&options.argv)
        .current_dir(&pyproject_dir)
        .stdin(Stdio::inherit());

    if background {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    }

    for (key, value) in &options.env {
        command.env(key, value);
    }

    command
        .spawn()
        .with_context(|| format!("Failed to spawn deno task '{}'", options.script))
}

fn terminate_child(child: &mut Child) -> Result<(), AnyError> {
    child
        .kill()
        .context("Failed to terminate task subprocess")?;
    Ok(())
}
