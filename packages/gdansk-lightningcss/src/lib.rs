use lightningcss::stylesheet::{
    MinifyOptions, ParserOptions, PrinterOptions, StyleSheet,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

fn transform_css_impl(code: &str, filename: &str, minify: bool) -> PyResult<String> {
    let mut parser_options = ParserOptions::default();
    parser_options.filename = filename.to_string();
    let mut stylesheet = StyleSheet::parse(code, parser_options)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    if minify {
        stylesheet
            .minify(MinifyOptions::default())
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
    }
    let printed = stylesheet
        .to_css(PrinterOptions {
            minify,
            ..PrinterOptions::default()
        })
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(printed.code)
}

#[pyfunction]
#[pyo3(signature = (code, filename, *, minify = true))]
fn transform_css(code: &str, filename: &str, minify: bool) -> PyResult<String> {
    transform_css_impl(code, filename, minify)
}

#[pyclass(module = "gdansk_lightningcss._core")]
struct LightningCssTransformer {
    minify: bool,
}

#[pymethods]
impl LightningCssTransformer {
    #[new]
    #[pyo3(signature = (*, minify = true))]
    fn new(minify: bool) -> Self {
        Self { minify }
    }

    fn transform(&self, code: &str, filename: &str) -> PyResult<String> {
        transform_css_impl(code, filename, self.minify)
    }
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<LightningCssTransformer>()?;
    m.add_function(wrap_pyfunction!(transform_css, m)?)?;
    Ok(())
}
