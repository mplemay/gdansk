use std::collections::BTreeMap;
use std::path::PathBuf;

use crate::task::RunTaskOptions;
use crate::types::error::BindingError;

pub(crate) fn normalize_run_task_options(
    task_cwd: PathBuf,
    script: String,
    argv: Vec<String>,
    env: BTreeMap<String, String>,
    host: Option<String>,
    port: Option<u16>,
) -> Result<RunTaskOptions, BindingError> {
    let script = script.trim().to_string();
    if script.is_empty() {
        return Err(BindingError::runtime("Task script name must not be empty"));
    }

    if host.as_ref().is_some_and(|value| value.trim().is_empty()) {
        return Err(BindingError::runtime("Task host must not be empty"));
    }

    if let Some(port) = port
        && !(1..=65_535).contains(&port)
    {
        return Err(BindingError::runtime(
            "Task port must be an integer between 1 and 65,535",
        ));
    }

    let host = host
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    if host.is_some() ^ port.is_some() {
        return Err(BindingError::runtime(
            "Long-running tasks require both host and port",
        ));
    }

    let task_cwd = task_cwd
        .canonicalize()
        .map_err(|error| BindingError::runtime(format!("Invalid task cwd: {error}")))?;

    if !task_cwd.is_dir() {
        return Err(BindingError::runtime(format!(
            "Task cwd must be a directory: {}",
            task_cwd.display()
        )));
    }

    Ok(RunTaskOptions {
        task_cwd,
        script,
        argv,
        env,
        host,
        port,
    })
}

pub(crate) fn ensure_task_success(result: crate::task::TaskResult) -> Result<(), BindingError> {
    if result.success() {
        Ok(())
    } else {
        Err(BindingError::runtime(format!(
            "Task exited with status {}",
            result.exit_code
        )))
    }
}
