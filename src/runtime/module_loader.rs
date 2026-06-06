use std::fs;

use deno_ast::{MediaType, ParseParams, SourceMapOption};
use deno_core::{
    ModuleLoadOptions, ModuleLoadReferrer, ModuleLoadResponse, ModuleLoader, ModuleSource,
    ModuleSourceCode, ModuleSpecifier, ModuleType, RequestedModuleType, ResolutionKind,
    error::ModuleLoaderError,
};
use deno_error::JsErrorBox;

#[derive(Debug, Default)]
pub(crate) struct PythonModuleLoader;

impl ModuleLoader for PythonModuleLoader {
    fn resolve(
        &self,
        specifier: &str,
        referrer: &str,
        _kind: ResolutionKind,
    ) -> Result<ModuleSpecifier, ModuleLoaderError> {
        deno_core::resolve_import(specifier, referrer).map_err(JsErrorBox::from_err)
    }

    fn load(
        &self,
        module_specifier: &ModuleSpecifier,
        _maybe_referrer: Option<&ModuleLoadReferrer>,
        options: ModuleLoadOptions,
    ) -> ModuleLoadResponse {
        ModuleLoadResponse::Sync(load_module_source(
            module_specifier,
            options.requested_module_type,
        ))
    }
}

fn load_module_source(
    module_specifier: &ModuleSpecifier,
    requested_module_type: RequestedModuleType,
) -> Result<ModuleSource, ModuleLoaderError> {
    let path = module_specifier
        .to_file_path()
        .map_err(|_| JsErrorBox::generic("Only file:// URLs are supported."))?;

    if matches!(
        requested_module_type,
        RequestedModuleType::Bytes | RequestedModuleType::Text | RequestedModuleType::Other(_)
    ) {
        let bytes = read_bytes(&path, module_specifier)?;
        return Ok(ModuleSource::new(
            match requested_module_type {
                RequestedModuleType::Bytes => ModuleType::Bytes,
                RequestedModuleType::Text => ModuleType::Text,
                RequestedModuleType::Other(module_type) => ModuleType::Other(module_type),
                _ => unreachable!(),
            },
            ModuleSourceCode::Bytes(bytes.into_boxed_slice().into()),
            module_specifier,
            None,
        ));
    }

    let media_type = MediaType::from_path(&path);
    let (module_type, should_transpile) = module_type_for_media_type(media_type, &path)?;
    if module_type == ModuleType::Json && requested_module_type != RequestedModuleType::Json {
        return Err(JsErrorBox::generic(
            "Attempted to load JSON module without specifying \"type\": \"json\" attribute in the import statement.",
        ));
    }

    let code = if should_transpile {
        ModuleSourceCode::String(transpile_module(module_specifier, &path, media_type)?.into())
    } else {
        ModuleSourceCode::Bytes(
            read_bytes(&path, module_specifier)?
                .into_boxed_slice()
                .into(),
        )
    };
    Ok(ModuleSource::new(module_type, code, module_specifier, None))
}

pub(crate) fn maybe_transpile_source(
    module_specifier: &ModuleSpecifier,
    source: String,
) -> Result<String, ModuleLoaderError> {
    let path = module_specifier
        .to_file_path()
        .map_err(|_| JsErrorBox::generic("Only file:// URLs are supported."))?;
    let media_type = MediaType::from_path(&path);
    let (module_type, should_transpile) = module_type_for_media_type(media_type, &path)?;
    if module_type != ModuleType::JavaScript {
        return Err(JsErrorBox::generic(format!(
            "Entrypoint must be JavaScript or TypeScript, got {:?}",
            path.extension()
        )));
    }
    if should_transpile {
        transpile_source(module_specifier, source, media_type)
    } else {
        Ok(source)
    }
}

fn module_type_for_media_type(
    media_type: MediaType,
    path: &std::path::Path,
) -> Result<(ModuleType, bool), ModuleLoaderError> {
    match media_type {
        MediaType::JavaScript | MediaType::Mjs | MediaType::Cjs => {
            Ok((ModuleType::JavaScript, false))
        }
        MediaType::Jsx
        | MediaType::TypeScript
        | MediaType::Mts
        | MediaType::Cts
        | MediaType::Dts
        | MediaType::Dmts
        | MediaType::Dcts
        | MediaType::Tsx => Ok((ModuleType::JavaScript, true)),
        MediaType::Json => Ok((ModuleType::Json, false)),
        MediaType::Wasm => Ok((ModuleType::Wasm, false)),
        _ => Err(JsErrorBox::generic(format!(
            "Unknown extension {:?}",
            path.extension()
        ))),
    }
}

fn read_bytes(
    path: &std::path::Path,
    module_specifier: &ModuleSpecifier,
) -> Result<Vec<u8>, ModuleLoaderError> {
    fs::read(path)
        .map_err(|error| JsErrorBox::generic(format!("Failed to load {module_specifier}: {error}")))
}

fn transpile_module(
    module_specifier: &ModuleSpecifier,
    path: &std::path::Path,
    media_type: MediaType,
) -> Result<String, ModuleLoaderError> {
    let source = fs::read_to_string(path).map_err(|error| {
        JsErrorBox::generic(format!("Failed to load {module_specifier}: {error}"))
    })?;
    transpile_source(module_specifier, source, media_type)
}

fn transpile_source(
    module_specifier: &ModuleSpecifier,
    source: String,
    media_type: MediaType,
) -> Result<String, ModuleLoaderError> {
    let parsed = deno_ast::parse_module(ParseParams {
        specifier: module_specifier.clone(),
        text: source.into(),
        media_type,
        capture_tokens: false,
        scope_analysis: false,
        maybe_syntax: None,
    })
    .map_err(JsErrorBox::from_err)?;
    let transpiled = parsed
        .transpile(
            &deno_ast::TranspileOptions {
                imports_not_used_as_values: deno_ast::ImportsNotUsedAsValues::Remove,
                decorators: deno_ast::DecoratorsTranspileOption::Ecma,
                ..Default::default()
            },
            &deno_ast::TranspileModuleOptions { module_kind: None },
            &deno_ast::EmitOptions {
                source_map: SourceMapOption::None,
                ..Default::default()
            },
        )
        .map_err(JsErrorBox::from_err)?
        .into_source();
    Ok(transpiled.text)
}

#[cfg(test)]
mod tests {
    use super::load_module_source;
    use deno_core::{ModuleSourceCode, ModuleSpecifier, ModuleType, RequestedModuleType};
    use std::{
        fs, io,
        path::{Path, PathBuf},
        time::{SystemTime, UNIX_EPOCH},
    };

    fn temp_dir(name: &str) -> io::Result<PathBuf> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock should be after the Unix epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "gdansk-module-loader-{name}-{}-{nanos}",
            std::process::id()
        ));
        fs::create_dir_all(&path)?;
        Ok(path)
    }

    fn specifier(path: &Path) -> ModuleSpecifier {
        ModuleSpecifier::from_file_path(path).expect("path should convert to file URL")
    }

    #[test]
    fn transpiles_typescript_modules_loaded_from_files() {
        let root = temp_dir("typescript").expect("temp dir should be created");
        let path = root.join("dep.ts");
        fs::write(
            &path,
            "export function double(value: number): number { return value * 2; }\n",
        )
        .expect("typescript module should be written");

        let module = load_module_source(&specifier(&path), RequestedModuleType::None)
            .expect("typescript module should load");

        let _ = fs::remove_dir_all(&root);
        assert_eq!(module.module_type, ModuleType::JavaScript);
        let ModuleSourceCode::String(code) = module.code else {
            panic!("typescript modules should be loaded as transpiled string source");
        };
        assert!(!code.as_str().contains(": number"));
    }

    #[test]
    fn rejects_json_imports_without_json_import_attribute() {
        let root = temp_dir("json").expect("temp dir should be created");
        let path = root.join("data.json");
        fs::write(&path, "{\"answer\":42}").expect("json module should be written");

        let result = load_module_source(&specifier(&path), RequestedModuleType::None);

        let _ = fs::remove_dir_all(&root);
        assert!(result.is_err());
    }
}
