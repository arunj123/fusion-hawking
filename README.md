# Fusion Hawking - High-Performance SOME/IP Stack

A lightweight, dependency-free SOME/IP library implemented in Rust, adhering to safety and performance standards. It includes bindings for Python and C++ to enable cross-language communication.

## Features

- **Core Protocol**: SOME/IP Header parsing and serialization.
- **Service Discovery**: Full SOME/IP-SD support with dynamic discovery, Offering, Subscribe/EventGroup, and TTL management.
- **Events & Fields**: Support for Publish/Subscribe pattern and Field notifications.
- **Transport**: UDP Support with Multicast capabilities.
- **Concurrency**: ThreadPool for handling concurrent requests.
- **Cross-Language Support**:
    - **Rust**: Native implementation with fully async-compatible SD machine.
    - **Python**: generated bindings and runtime with Event support.
    - **C++**: High-performance runtime with modern C++14 support.
- **IDL Compiler**: Python-based tool (`tools/codegen`) to generate code from simple Python dataclasses. Supports recursive types and synchronous RPC. See [IDL Documentation](docs/IDL.md).

## Prerequisites

The `fusion` tool will verify these for you, but you need:
- **Rust**: Latest Stable (install via `rustup`).
- **Python**: Python 3.8+.
- **C++ Compiler**: CMake 3.10+ and MSVC/GCC.

**Note**: The tool automatically attempts to install missing components like `cargo-llvm-cov` and `llvm-tools-preview`.

## Quick Start

### 1. Build & Run All Demos (Windows)

The easiest way to see everything in action is the new automation dashboard:

```powershell
.\fusion.bat
```

This will:
1.  **Check Toolchain**: Verifies Rust, Python, CMake, and Coverage tools.
2.  **Dashboard**: Starts a local web server (http://localhost:8000) to show live progress.
3.  **Build**: Compiles Rust, Python bindings, and C++.
4.  **Test**: Runs unit tests for all languages.
5.  **Simulate**: Runs the integrated multi-process demo (Rust/Python/C++ interacting).
6.  **Report**: Generates a comprehensive HTML report with coverage data.

### 2. Linux / WSL

```bash
./fusion.sh
```

## Architecture

- **`src/`**: Core source code (Rust, Python, C++).
- **`tools/fusion/`**: Automation infrastructure (Python).
- **`examples/`**: Demo applications.

## Testing & Verification

The `fusion` tool unifies all testing steps.

### Dashboard Features
The dashboard (http://localhost:8000) provides a real-time view of the build and test process:
- **Live Status**: Watch steps complete in real-time.
- **File Explorer**: Browse logs, source code, and generated configs directly in the UI.
- **Inline Viewer**: View logs and code with **Syntax Highlighting** (no downloads required).
- **Run Controls**: Re-run specific tests directly from the dashboard.
- **Coverage Links**: Click "PASS" on coverage steps to view detailed HTML reports.

### Reports & Artifacts
After a run, artifacts are organized in `logs/latest/`:
- **Dashboard**: `index.html` (entry point).
- **Coverage**: 
    - `coverage/rust/index.html`
    - `coverage/python/index.html`
    - `coverage/cpp/index.html`
- **Raw Logs**: Categorized into:
    - `raw_logs/build/` (Compilation logs)
    - `raw_logs/test/` (Unit test logs)
    - `raw_logs/demo/` (Integration logs with command headers)
- **Configs**: `configs/` (Snapshot of generated bindings and build configurations)

### Manual Run
You can still run individual steps if preferred, but `fusion.bat` is recommended.

```bash
# Run only unit tests
cargo test
python -m unittest discover tests
```

## Integrating with Your Project

Fusion Hawking is designed to be easily integrated into larger projects.

### 1. Rust
Add it as a git dependency in your `Cargo.toml`:
```toml
[dependencies]
fusion-hawking = { git = "https://github.com/arunj123/fusion-hawking.git" }
```

### 2. Python
You can install the Python package directly from the repo:
```bash
pip install "git+https://github.com/arunj123/fusion-hawking.git#egg=fusion-hawking&subdirectory=src/python"
```
Or simply add `src/python` to your `PYTHONPATH`.

### 3. C++
Use CMake's `FetchContent` or `add_subdirectory`:
```cmake
add_subdirectory(path/to/fusion-hawking)
target_link_libraries(your_app PRIVATE fusion_hawking_cpp)
```

### 4. Custom Code Generation (IDL)
To generate your own service bindings:
1. Define your interface in a Python file using dataclasses (see `examples/integrated_apps/interface.py`).
2. Run the generator:
```bash
python -m tools.codegen.main your_interface.py
```
Bindings will be generated for all three languages.

## References

- **SOME/IP Protocol**: `AUTOSAR_PRS_SOMEIPProtocol`
- **SOME/IP Service Discovery**: `AUTOSAR_PRS_SOMEIPServiceDiscoveryProtocol`

## Licensing

MIT License.
