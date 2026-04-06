use pyo3::{
    exceptions::PyValueError,
    prelude::*,
    types::{PyDict, PyTuple},
};

#[pyclass(module = "gdansk_bundler._core", subclass, skip_from_py_object)]
pub struct Plugin {
    name: String,
}

#[pymethods]
impl Plugin {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, PyDict>>) -> Self {
        Self {
            name: String::new(),
        }
    }

    #[pyo3(signature = (*, name=None, id=None))]
    fn __init__(&mut self, name: Option<String>, id: Option<String>) -> PyResult<()> {
        let chosen = match (name, id) {
            (Some(n), None) => n,
            (None, Some(i)) => i,
            (Some(n), Some(i)) => {
                if n != i {
                    return Err(PyValueError::new_err(
                        "Plugin name and id must match when both are provided",
                    ));
                }
                n
            }
            (None, None) => {
                return Err(PyValueError::new_err(
                    "Plugin requires keyword argument name or id",
                ));
            }
        };
        if chosen.is_empty() {
            return Err(PyValueError::new_err(
                "Plugin name or id must be a non-empty string",
            ));
        }
        self.name = chosen;
        Ok(())
    }

    #[getter]
    fn name(slf: PyRef<'_, Self>) -> String {
        slf.name.clone()
    }

    #[getter]
    fn id(slf: PyRef<'_, Self>) -> String {
        slf.name.clone()
    }
}
