use deno_core::extension;
use deno_core::snapshot::CreateSnapshotOptions;
use deno_core::snapshot::create_snapshot;
use std::env;
use std::fs;
use std::path::PathBuf;

extension!(
    gdansk_runtime_ext,
    esm_entry_point = "gdansk:runtime",
    esm = [
      dir "src",
      "gdansk:runtime" = "runtime.js",
    ],
);

fn main() {
    let options = CreateSnapshotOptions {
        cargo_manifest_dir: env!("CARGO_MANIFEST_DIR"),
        startup_snapshot: None,
        extensions: vec![gdansk_runtime_ext::init()],
        with_runtime_cb: None,
        skip_op_registration: false,
        extension_transpiler: None,
    };

    let snapshot = create_snapshot(options, None).expect("Error creating runtime snapshot");

    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is not set"));
    let file_path = out_dir.join("GDANSK_RUNTIME_SNAPSHOT.bin");
    fs::write(file_path, snapshot.output).expect("Failed to write runtime snapshot");

    println!("cargo:rerun-if-changed=build.rs");
    for path in snapshot.files_loaded_during_snapshot {
        println!("cargo:rerun-if-changed={}", path.display());
    }
}
