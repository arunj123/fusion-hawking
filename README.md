# Fusion Hawking - High-Performance SOME/IP Stack

A lightweight, dependency-free SOME/IP library implemented in Rust, adhering to safety and performance standards. It includes bindings for Python and C++ to enable cross-language communication.

## Features

- **Core Protocol**: SOME/IP Header parsing and serialization.
- **Service Discovery**: Full SOME/IP-SD support with dynamic discovery, Offering, Subscribe/EventGroup, and TTL management.
- **Events & Fields**: Support for Publish/Subscribe pattern and Field notifications.
- **Transport**: UDP Support with Multicast capabilities (`224.0.0.1`).
- **Concurrency**: ThreadPool for handling concurrent requests.
- **Cross-Language Support**:
    - **Rust**: Native implementation with fully async-compatible SD machine.
    - **Python**: generated bindings and runtime with Event support.
    - **C++**: High-performance runtime with modern C++14 support.
- **IDL Compiler**: Python-based tool (`tools/codegen`) to generate code from simple Python dataclasses.

## Prerequisites

- **Rust**: Latest Stable (install via `rustup`).
- **Python**: Python 3.8+ (with `pytest` for tests).
- **C++ Compiler**: CMake 3.10+ and MSVC/GCC.
- **PowerShell**: For running automation scripts (Windows).

## Quick Start

### 1. Build & Run All Demos (Windows)

The easiest way to see everything in action is the automation script:

```powershell
.\run_demos.ps1
```

This will:
1. Generate code from `examples/interface.py`.
2. Build Rust, Python, and C++ runtimes.
3. Launch 3 processes:
   - **Rust App**: Provides `MathService` (0x1001), Consumes `SortService` events.
   - **C++ App**: Provides `SortService` (0x3001), Consumes `MathService`.
   - **Python App**: Provides `StringService` (0x2001), Consumes `MathService` & `StringService`.

### 2. Manual Run

**Step 1: Generate Code**
```bash
python -m tools.codegen.main examples/interface.py
```

**Step 2: Start Rust App**
```bash
cargo run --example rust_app
```

**Step 3: Start Python App**
```bash
# Make sure to set PYTHONPATH
$env:PYTHONPATH="src/python;build"
python examples/python_app/main.py
```

**Step 4: Start C++ App**
```bash
mkdir build
cd build
cmake ..
cmake --build . --config Release
.\Release\cpp_app.exe
```

### 3. Generator Usage

The project now uses a modular code generator package.

1.  **Define Interface**: Create a Python file defining data structures and services using decorators.
    ```python
    # examples/interface.py
    from dataclasses import dataclass
    # Import mock decorators ...
    
    @service(id=0x1001)
    class MathService:
        @method(id=1)
        def add(self, a: int, b: int) -> int: ...
    ```

2.  **Generate Code**:
    ```bash
    python -m tools.codegen.main examples/interface.py
    ```

3.  **Use generated code**:
    - Rust: `src/generated/mod.rs` (use `SomeIpRuntime`)
    - Python: `src/generated/bindings.py` & `src/generated/runtime.py`
    - C++: `src/generated/bindings.h`

## Architecture

- **`src/codec`**: Serialization/Deserialization of SOME/IP headers and payloads.
- **`src/sd`**: Service Discovery state machine and packet handling.
- **`src/transport`**: UDP/TCP abstractions.
- **`src/runtime`**: Execution handling (ThreadPool).
- **`tools/`**: Code generation tools.

## Licensing

MIT License.
