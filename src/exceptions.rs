use pyo3::exceptions::PyException;

pyo3::create_exception!(_core, DenoError, PyException);
pyo3::create_exception!(_core, DenoRuntimeError, DenoError);
pyo3::create_exception!(_core, DenoModuleError, DenoError);
pyo3::create_exception!(_core, DenoJavaScriptError, DenoError);
