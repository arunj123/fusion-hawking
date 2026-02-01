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

### 2. Run the Demo (Manual)

The demo consists of three components communicating via SOME/IP and SD over the loopback interface.

**Step 1: Start the Rust Service (Math Service)**
This service offers a Math function (Add/Sub) on port 30501.
```bash
cargo run --example rust_demo
```

**Step 2: Start the Python Client/Service**
This script listens for SD offers, discovers the Rust service, and sends requests. It also responds to queries (though the Rust demo focuses on being a server).
```bash
# In a new terminal
python examples/python_app/main.py
```

 You should see output indicating:
 - Rust Service offering 0x1001.
 - Python Client discovering 0x1001.
 - Python Client sending requests and receiving responses.

### 3. Run the Demo (Script)

Windows (PowerShell):
```powershell
./run_demos.ps1
```

### 4. Run Tests

To run unit tests and integration verifications:
```bash
cargo test
# or
./run_tests.ps1
```

## IDL Workflow

1.  **Define Interface**: Create a Python file defining data structures.
    ```python
    # examples/interface.py
    from dataclasses import dataclass
    @dataclass
    class MyMessage:
        id: int
        data: List[int]
    ```

2.  **Generate Code**:
    ```bash
    python tools/codegenerator.py examples/interface.py
    ```

3.  **Use generated code**:
    - Rust: `src/generated/mod.rs`
    - Python: `src/generated/bindings.py`
    - C++: `src/generated/bindings.hpp`

## Architecture

- **`src/codec`**: Serialization/Deserialization of SOME/IP headers and payloads.
- **`src/sd`**: Service Discovery state machine and packet handling.
- **`src/transport`**: UDP/TCP abstractions.
- **`src/runtime`**: Execution handling (ThreadPool).
- **`tools/`**: Code generation tools.

## Licensing

MIT License.
