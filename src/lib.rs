mod bundle;
mod plugins;
mod runtime;

#[cfg(not(test))]
use pyo3::prelude::*;

#[cfg(test)]
mod test_support {
    use std::sync::{Mutex, OnceLock};

    pub(crate) fn js_runtime_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }
}

#[cfg(not(test))]
#[pymodule]
mod _core {
    #[pymodule_export]
    use super::bundle::{LightningCSS, Page, VitePlugin, bundle};
    #[pymodule_export]
    use super::runtime::run;
}
