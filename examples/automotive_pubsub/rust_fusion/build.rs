//! Build script for automotive_pubsub Rust Fusion node.
//! Calls the Fusion Hawking codegen tool to generate per-service Rust bindings.

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let out_dir = env::var("OUT_DIR").unwrap();
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();

    // Project root is 3 levels up from examples/automotive_pubsub/rust_fusion
    let project_root = PathBuf::from(&manifest_dir)
        .parent().unwrap()
        .parent().unwrap()
        .parent().unwrap()
        .to_path_buf();

    let gen_dir = format!("{}/generated/automotive_pubsub", out_dir);

    let status = Command::new("python")
        .args([
            "-m", "tools.codegen.main",
            "--project", "automotive_pubsub",
            "--lang", "rust",
            "--module", "examples.automotive_pubsub.idl",
            "--output-dir", &gen_dir,
        ])
        .current_dir(&project_root)
        .env("PYTHONPATH", project_root.join("src").join("python").to_str().unwrap())
        .status()
        .expect("Failed to run codegen. Is Python available?");

    if !status.success() {
        panic!("Codegen failed for automotive_pubsub");
    }

    // Rerun if IDL changes
    println!("cargo:rerun-if-changed=../../automotive_pubsub/idl/");
    println!("cargo:rerun-if-changed=../idl/");
}
