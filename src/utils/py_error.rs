use pyo3::{
    PyErr,
    exceptions::{PyTypeError, PyValueError},
};

use crate::exceptions::{GdanskJavaScriptError, GdanskModuleError, GdanskRuntimeError};
use crate::types::error::BindingError;

pub(crate) fn from_binding_error(error: BindingError) -> PyErr {
    match error {
        BindingError::ValueConversion { message } => {
            if message.contains("BigInt") || message.contains("Symbol") {
                PyTypeError::new_err(message)
            } else {
                PyValueError::new_err(message)
            }
        }
        BindingError::Runtime { message } => GdanskRuntimeError::new_err(message),
        BindingError::ModuleLoad { message } => GdanskModuleError::new_err(message),
        BindingError::MissingRunExport { .. } | BindingError::NonFunctionRunExport { .. } => {
            GdanskModuleError::new_err(error.message())
        }
        BindingError::JavaScript { .. } => GdanskJavaScriptError::new_err(error.message()),
    }
}
