use pyo3::{prelude::*, types::PyBool};

use crate::{BundlerConfigState, unsupported_feature_error};

use super::parse::{
    extract_string, extract_string_sequence, parse_define, parse_devtools, parse_external, parse_input,
    parse_inject, parse_manual_code_splitting, parse_optional_cwd, parse_output_config, parse_platform,
    parse_resolve_options, parse_tsconfig, parse_treeshake,
};
use super::plugins::parse_plugins;

#[allow(clippy::too_many_arguments)]
pub(crate) fn bundler_config_from_python(
    py: Python<'_>,
    input: &Bound<'_, PyAny>,
    cwd: Option<&Bound<'_, PyAny>>,
    resolve: Option<&Bound<'_, PyAny>>,
    devtools: Option<&Bound<'_, PyAny>>,
    output: Option<&Bound<'_, PyAny>>,
    plugins: Option<&Bound<'_, PyAny>>,
    watch: Option<&Bound<'_, PyAny>>,
    platform: Option<&Bound<'_, PyAny>>,
    context: Option<&Bound<'_, PyAny>>,
    tsconfig: Option<&Bound<'_, PyAny>>,
    shim_missing_exports: Option<&Bound<'_, PyAny>>,
    keep_names: Option<&Bound<'_, PyAny>>,
    profiler_names: Option<&Bound<'_, PyAny>>,
    define: Option<&Bound<'_, PyAny>>,
    drop_labels: Option<&Bound<'_, PyAny>>,
    inject: Option<&Bound<'_, PyAny>>,
    external: Option<&Bound<'_, PyAny>>,
    treeshake: Option<&Bound<'_, PyAny>>,
    manual_code_splitting: Option<&Bound<'_, PyAny>>,
) -> PyResult<BundlerConfigState> {
    if let Some(watch) = watch {
        let watch_is_disabled =
            watch.is_instance_of::<PyBool>() && !watch.cast::<PyBool>()?.extract::<bool>()?;
        if !watch_is_disabled {
            return Err(unsupported_feature_error("Bundler.watch"));
        }
    }

    let plugins = parse_plugins(plugins)?;

    let input = parse_input(input)?;
    let resolve = parse_resolve_options(resolve)?;
    let (devtools_enabled, devtools_session_id) = parse_devtools(devtools)?;
    let default_output = parse_output_config(output, "Bundler.output")?;
    let platform = parse_platform(platform)?;
    let context = context
        .map(|v| extract_string(v, "Bundler.context must be a string"))
        .transpose()?;
    let tsconfig = parse_tsconfig(tsconfig)?;
    let shim_missing_exports = shim_missing_exports
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| {
                    pyo3::exceptions::PyTypeError::new_err(
                        "Bundler.shim_missing_exports must be a boolean",
                    )
                })?
                .extract()
        })
        .transpose()?;
    let keep_names = keep_names
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| pyo3::exceptions::PyTypeError::new_err("Bundler.keep_names must be a boolean"))?
                .extract()
        })
        .transpose()?;
    let profiler_names = profiler_names
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| {
                    pyo3::exceptions::PyTypeError::new_err("Bundler.profiler_names must be a boolean")
                })?
                .extract()
        })
        .transpose()?;
    let define = parse_define(define)?;
    let drop_labels = drop_labels
        .map(|v| extract_string_sequence(v, "Bundler.drop_labels must be a sequence of strings"))
        .transpose()?;
    let inject = parse_inject(inject)?;
    let external = parse_external(py, external)?;
    let treeshake = parse_treeshake(treeshake)?;
    let manual_code_splitting = parse_manual_code_splitting(manual_code_splitting)?;

    Ok(BundlerConfigState {
        input,
        cwd: parse_optional_cwd(cwd)?,
        resolve,
        devtools_enabled,
        devtools_session_id,
        default_output,
        platform,
        context,
        tsconfig,
        shim_missing_exports,
        keep_names,
        profiler_names,
        define,
        drop_labels,
        inject,
        external,
        treeshake,
        manual_code_splitting,
        plugins,
    })
}
