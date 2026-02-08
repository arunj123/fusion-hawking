# Fusion-Hawking User Guide

> **See Also:** [Architecture Overview](architecture.md) | [IDL Reference](IDL.md) | [Design Document](design_and_requirements.md)

## Overview

Fusion-Hawking is a pure SOME/IP stack implementation supporting Rust, Python, and C++ with zero external dependencies. This guide covers day-to-day usage for application developers.

---

## Quick Start

### 1. Run the Automation Dashboard

The fastest way to build, test, and verify everything:

```powershell
# Windows
.\fusion.bat

# Linux/WSL
./fusion.sh
```

This launches a live dashboard at http://localhost:8000 showing build progress, test results, and coverage reports.

### 2. Define Services

Create an interface file using Python dataclasses:

```python
# examples/integrated_apps/interface.py
class MathService:
    SERVICE_ID = 0x1001
    
    def add(self, a: int, b: int) -> int:
        """Synchronous RPC - waits for response."""
        pass
    
    def log(self, message: str):
        """Fire-and-forget - returns immediately."""
        pass
```

> **Tip:** See the [IDL Documentation](IDL.md) for the full type system and event definitions.

### 3. Generate Bindings

```bash
python -m tools.codegen.main examples/integrated_apps/interface.py
```

Generated files appear in `build/generated/{rust,python,cpp}/`.

---

## Configuration

Applications load a shared `config.json` that defines the network topology:

```json
{
  "endpoints": {
    "math_ep": {
      "interface": "eth0",
      "ip": "127.0.0.1",
      "port": 30509,
      "protocol": "udp"
    },
    "sd_mcast": {
      "ip": "224.0.0.1",
      "port": 30490,
      "protocol": "udp"
    }
  },
  "instances": {
    "my_instance": {
      "providing": {
        "math-service": {
          "service_id": 4097,
          "instance_id": 1,
          "endpoint": "math_ep"
        }
      },
      "required": {
        "string-service": { 
          "service_id": 4098,
          "endpoint": "math_ep" 
        }
      },
      "sd": {
        "multicast_endpoint": "sd_mcast"
      }
    }
  }
}
```

> **Details:** See [Design & Requirements](design_and_requirements.md#2-json-configuration-schema) for the full schema including multicast, IPv6, and static routing options.

---

## Runtime API

All three language runtimes share the same semantics:

### Rust

```rust
let rt = SomeIpRuntime::load("config.json", "my_instance");
rt.offer_service("math-service", Box::new(MathServiceImpl));
rt.run();
```

### Python

```python
rt = SomeIpRuntime("config.json", "my_instance")
rt.offer_service("math-service", MathServiceStub())
rt.start()
```

### C++ (C++23)

```cpp
SomeIpRuntime rt("config.json", "my_instance");
rt.offer_service("math-service", &my_service_impl);
rt.run();
```

> **Architecture:** See the [Cross-Language Runtime diagram](architecture.md#cross-language-runtime-architecture) for internals.

---

## Logging

All runtimes use a pluggable logger interface for DLT compatibility:

| Language | Interface | Default |
|----------|-----------|---------|
| Rust | `FusionLogger` trait | `ConsoleLogger` |
| Python | `ILogger` base class | `ConsoleLogger` |
| C++ | `ILogger` abstract class | `ConsoleLogger` |

Example (Python):

```python
from fusion_hawking.logger import ILogger, LogLevel

class MyLogger(ILogger):
    def log(self, level: LogLevel, component: str, msg: str):
        print(f"[{level.name}] {component}: {msg}")

rt = SomeIpRuntime("config.json", "my_instance", logger=MyLogger())
```

---

## Running Examples

The `examples/` directory contains four categories:

| Directory | Purpose | Docs |
|-----------|---------|------|
| `simple_no_sd/` | Raw wire protocol (no Service Discovery) | [Examples README](../examples/README.md#2-simple-no-sd) |
| `integrated_apps/` | Full runtime with RPC | [Examples README](../examples/README.md#3-integrated-apps) |
| `automotive_pubsub/` | Pub/Sub event pattern | [Examples README](../examples/README.md#4-automotive-pub-sub) |
| `sd_demos/` | Service Discovery isolation | [Examples README](../examples/README.md#1-raw-service-discovery) |

---

## Testing

### Automated Testing

```powershell
.\fusion.bat   # Runs everything with live dashboard
```

### Manual Testing

```bash
# Rust only
cargo test

# Python only  
pytest tests/

# C++ only
cmake --build build --config Release
.\build\Release\cpp_test.exe
```

> **Coverage Matrix:** See [Test Matrix](test_matrix.md) for detailed coverage by component.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port in use | Check `config.json` for conflicting port assignments |
| Service not discovered | Ensure multicast group `224.0.0.1:30490` is accessible |
| Timeout on RPC | Verify server is running and firewall allows UDP |
| Build failure | Run `.\fusion.bat` to verify all toolchains |

---

## Next Steps

- **Understand the internals:** [Architecture Document](architecture.md)
- **Learn the type system:** [IDL Documentation](IDL.md)
- **Review test coverage:** [Test Matrix](test_matrix.md)
- **Explore examples:** [Examples README](../examples/README.md)
