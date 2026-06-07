use pyo3::exceptions::PyException;

pyo3::create_exception!(_core, GdanskError, PyException);
pyo3::create_exception!(_core, GdanskRuntimeError, GdanskError);
pyo3::create_exception!(_core, GdanskModuleError, GdanskError);
pyo3::create_exception!(_core, GdanskJavaScriptError, GdanskError);
