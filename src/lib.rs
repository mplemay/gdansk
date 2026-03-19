mod bundle;
mod plugins;
mod runtime;

#[cfg(not(test))]
use pyo3::prelude::*;

#[cfg(not(test))]
#[pymodule]
mod _core {
    #[pymodule_export]
    use super::bundle::{Page, bundle, bundle_with_plugins};
    #[pymodule_export]
    use super::runtime::{JsPluginRunner, run};
}
