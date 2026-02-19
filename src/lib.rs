mod bundle;
mod runtime;

#[cfg(not(test))]
use pyo3::prelude::*;

#[cfg(not(test))]
#[pymodule]
mod _core {
    #[pymodule_export]
    use super::bundle::bundle;
    #[pymodule_export]
    use super::runtime::Runtime;
}
