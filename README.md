# Fusion Hawking - High-Performance SOME/IP Stack

A lightweight, dependency-free SOME/IP library implemented in Rust, adhering to **AUTOSAR R22-11** (PRS_SOMEIPProtocol & PRS_SOMEIPServiceDiscoveryProtocol) safety and performance standards. It includes bindings for Python and C++ to enable cross-language communication.

## Features

- **Core Protocol**: SOME/IP Header parsing and serialization.
- **Transport**: UDP Support with Multicast capabilities.
- **Service Discovery**: Full SOME/IP-SD support with multi-interface discovery, offering, and TTL management.
- **Packet Dump**: Native protocol-level packet dumping for diagnostics across all runtimes.
- **Concurrency**: ThreadPool for handling concurrent requests.
- **Cross-Language Support**:
    - **Rust**: Native implementation with fully async-compatible SD machine.
    - **Python**: Generated bindings and runtime with Event support.
    - **C++**: High-performance runtime with modern C++23 support.
    - **JavaScript/TypeScript**: Pure TS implementation running on Node.js (no native bindings required).
- **Automotive Pub-Sub Demos**: Included examples demonstrating cross-language (Rust, C++, Python, JS/TS) publish-subscribe patterns typical of automotive middleware.
- **IDL Compiler**: Python-based tool (`tools/codegen`) to generate code from simple Python dataclasses. Supports recursive types and synchronous RPC. See [IDL Documentation](docs/IDL.md).


## Prerequisites

The `fusion` tool will verify these for you, but you need:
- **Rust**: Latest Stable (install via `rustup`).
- **Python**: Python 3.8+.
- **Node.js**: v18+ (for JS/TS support).
- **C++ Compiler**: CMake 3.10+ and MSVC/GCC.
- **Linux/WSL dependencies**: `sudo apt install build-essential cmake python3-venv lcov libssl-dev`.


**Note**: The tool automatically attempts to install missing components like `cargo-llvm-cov` and `llvm-tools-preview`.

## Quick Start

### 1. Build & Run All Demos (Windows)

The easiest way to see everything in action is the automation dashboard:

```powershell
.\fusion.bat
```

This will:
1.  **Check Toolchain**: Verifies Rust, Python, CMake, and Coverage tools.
2.  **Dashboard**: Starts a local web server (http://localhost:8000) to show live progress.
3.  **Build**: Compiles Rust, Python bindings, C++, and TypeScript.
4.  **Test**: Runs unit tests for all languages (Rust, Python, C++, JS).
5.  **Simulate**: Runs the integrated multi-process demo (Rust/Python/C++/JS interacting).
6.  **Report**: Generates a comprehensive HTML report with coverage data.


### 2. Linux / WSL

```bash
./fusion.sh
```

### 3. Advanced Usage (CLI)

The automation tool supports granular execution:

```bash
# Run specific demo
python -m tools.fusion.main --stage demos --demo simple      # Run Simple Demo
python -m tools.fusion.main --stage demos --demo integrated  # Run Integrated Demo
python -m tools.fusion.main --stage demos --demo pubsub      # Run PubSub Demo

# Run specific build stages
python -m tools.fusion.main --stage codegen                  # Generate bindings only
python -m tools.fusion.main --stage build --target rust      # Build Rust only
python -m tools.fusion.main --stage test --target cpp        # Test C++ only
python -m tools.fusion.main --stage test --target js         # Test JS only
```

## Architecture

- **`src/`**: Core source code (Rust, Python, C++, JS).
- **`tools/fusion/`**: Automation infrastructure (Python).
- **`examples/`**: Demo applications (including Automotive Pub-Sub).

> **Detailed Architecture:** See [Architecture Document](docs/architecture.md) for diagrams covering the interface-centric deployment model, layers, and service discovery.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | Visual architecture with PlantUML diagrams |
| [User Guide](docs/user_guide.md) | Day-to-day usage and API reference |
| [IDL Reference](docs/IDL.md) | Type system and code generation |
| [Design Doc](docs/design_and_requirements.md) | Design decisions and requirements |
| [Test Matrix](docs/test_matrix.md) | Coverage and verification status |
| [Examples](examples/README.md) | Demo applications walkthrough |

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
    - `coverage/js/index.html`
- **Raw Logs**: Categorized into `raw_logs/build/`, `raw_logs/test/`, and `raw_logs/demo/`.

### CI/CD Validation
The project includes a robust CI/CD pipeline implemented via GitHub Actions (`.github/workflows/fusion.yml`).

**Key Pipeline Stages:**
1.  **Codegen**: Generates service bindings for all languages.
2.  **Multi-Platform Build**: Builds binaries/packages for Ubuntu and Windows (x64 and ARM64).
3.  **Unit Tests**: Executes test suites for Rust, Python, C++, and JS.
4.  **Integration Demos**: Runs the "Automotive Pub-Sub" and "Integrated App" demos.
5.  **Virtual Network (VNet)**: On Linux, performs high-fidelity network testing using namespaces and `setup_vnet.sh`.

**How to verify locally:**
The CI/CD pipeline can be fully simulated and verified locally using the automation toolkit:
- **Windows**: Run `.\fusion.bat` to execute the full build, test, demo, and coverage pipeline.
- **Linux/WSL**: Run `./fusion.sh` to execute the pipeline natively or in WSL.
- **Dashboard**: A live dashboard will be hosted at `http://localhost:8000` to monitor CI progress in real-time.

**How to verify via GitHub Actions:**
- **Trigger**: Every push or PR to `main` triggers a run.
- **Status**: View badge or Actions tab.
- **Artifacts**: CI uploads full `logs` and `generated` bindings as artifacts for every run.

## Integrating with Your Project

### 1. Rust
Add as a git dependency in `Cargo.toml`:
```toml
[dependencies]
fusion-hawking = { git = "https://github.com/arunj123/fusion-hawking.git" }
```

### 2. Python
Install directly via pip:
```bash
pip install "git+https://github.com/arunj123/fusion-hawking.git#egg=fusion-hawking&subdirectory=src/python"
```

### 3. C++
Use CMake's `FetchContent` or `add_subdirectory`:
```cmake
add_subdirectory(path/to/fusion-hawking)
target_link_libraries(your_app PRIVATE fusion_hawking_cpp)
```

### 4. JavaScript/TypeScript (Node.js)
The JS/TS runtime is pure TypeScript. Install dependencies and build:
```bash
cd src/js && npm install && npm run build
```
Then import in your project:
```typescript
import { SomeIpRuntime } from 'fusion-hawking/runtime';
```
Demos are available in `examples/integrated_apps/js_app` and `examples/automotive_pubsub/js_adas`.

### 5. Custom Code Generation (IDL)
1. Define your interface in a Python file using dataclasses.
2. Run the generator:
```bash
python -m tools.codegen.main your_interface.py --all
```
This generates bindings for Rust, Python, C++, and TypeScript simultaneously.

## Intended Use & Disclaimer

This project is an independent implementation of the SOME/IP protocol and is intended primarily for **hobbyist experimentation, educational purposes, and non-critical test environments**.

> [!IMPORTANT]
> **AUTOSAR** is a registered trademark of the AUTOSAR partner companies. SOME/IP and SOME/IP-SD are open standards defined by AUTOSAR. This project is **not** affiliated with, endorsed by, or sponsored by AUTOSAR.

### Usage Disclaimer
- **No Warranty**: This software is provided "as is," without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement.
- **Liability**: In no event shall the authors or copyright holders be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.
- **User Responsibility**: Any individual or organization choosing to use this implementation does so at their own risk. It is the user's responsibility to ensure that its use complies with any relevant safety standards or legal requirements in their specific application context.

This implementation is **not** certified for use in production automotive systems or any safety-critical applications.

## References

- **SOME/IP Protocol**: `AUTOSAR_PRS_SOMEIPProtocol`
- **SOME/IP Service Discovery**: `AUTOSAR_PRS_SOMEIPServiceDiscoveryProtocol`

## Licensing

MIT License.
