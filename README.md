# Fusion Hawking - High-Performance SOME/IP Stack

A lightweight, dependency-free SOME/IP library implemented in Rust, adhering to safety and performance standards. It includes bindings for Python and C++ to enable cross-language communication.

## Features

- **Core Protocol**: SOME/IP Header parsing and serialization.
- **Service Discovery**: SOME/IP-SD packet format, state machine, and dynamic service discovery.
- **Transport**: UDP Support with Multicast capabilities.
- **Concurrency**: ThreadPool for handling concurrent requests.
- **Cross-Language Support**:
    - **Rust**: Native implementation.
    - **Python**: Generated bindings and runtime.
    - **C++**: Generated headers and serialization logic.
- **IDL Compiler**: Python-based tool (`tools/codegenerator.py`) to generate code from simple Python dataclasses.

## Prerequisites

- **Rust**: Latest Stable (install via `rustup`).
- **Python**: Python 3.8+.
- **C++ Compiler**: GCC or MSVC (for building C++ examples, though the demo uses Python/Rust primarily).

## Quick Start

### 1. Build the Project

```bash
cargo build --release
```

### 2. Run the Demo

The demo showcases the "Zero Boilerplate" Runtime architecture where services are automatically discovered and traffic is routed.

**Step 1: Start the Rust Service (Math Service)**
```bash
cargo run --example rust_app
```

**Step 2: Start the Python Client/Service**
```bash
# In a new terminal
python examples/python_app/main.py
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
