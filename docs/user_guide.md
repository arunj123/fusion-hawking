# Fusion-Hawking User Guide

> **See Also:** [Architecture Overview](architecture.md) | [IDL Reference](IDL.md) | [Design Document](design_and_requirements.md)

## Overview

Fusion-Hawking is a pure SOME/IP stack implementation supporting Rust, Python, C++, and JavaScript/TypeScript with zero external dependencies. This guide covers day-to-day usage for application developers.

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
# Generate for a specific language
python -m tools.codegen.main examples/integrated_apps/interface.py --lang rust

# Generate for ALL supported languages (Rust, Python, C++, TS)
python -m tools.codegen.main examples/integrated_apps/interface.py --all
```

Generated files appear in `build/generated/{rust,python,cpp,js}/`.

---

## Configuration

Applications load a shared `config.json` that defines the network topology. The same configuration is used across all language runtimes.

```json
{
  "interfaces": {
    "lo": {
      "name": "lo",
      "endpoints": {
        "sd_mcast": { "ip": "224.0.0.1", "port": 30490, "version": 4 },
        "service_ep": { "ip": "127.0.0.1", "port": 30500, "version": 4, "protocol": "udp" }
      },
      "sd": { "endpoint": "sd_mcast" }
    }
  },
  "instances": {
    "my_instance": {
      "bind": {
        "interface": "lo",
        "endpoint": "service_ep"
      },
      "providing": {
        "math-service": {
          "service_id": 4097,
          "instance_id": 1,
          "endpoint": "service_ep"
        }
      },
      "required": {
        "string-service": { 
          "service_id": 4098,
          "preferred_interface": "lo" 
        }
      }
    }
  }
}
```

> **Details:** See [Design & Requirements](design_and_requirements.md#2-interface-centric-configuration-schema) for the full schema details.

---

## Runtime API

All runtimes share the same semantics and service-oriented lifecycle.

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

High-performance implementation with minimal overhead.

```cpp
SomeIpRuntime rt("config.json", "my_instance");
rt.offer_service("math-service", &my_service_impl);
rt.run();
```

### JavaScript/TypeScript (Node.js 18+)

Pure TypeScript implementation. No native addons required.

```typescript
import { SomeIpRuntime } from 'fusion-hawking';

const rt = new SomeIpRuntime();
await rt.loadConfigFile('config.json', 'js_app_instance');

// Method Handler
rt.registerHandler(0x0001, (header, payload) => {
    const result = handleRequest(payload);
    return Buffer.from(result);
});

// Event Subscription
rt.subscribeEvent(0x1001, 0x01, (payload) => {
    console.log("Received event notification:", payload);
});

await rt.start();
```

---

## CI/CD Validation & Verification

### The Automation Pipeline
Fusion Hawking uses a multi-stage CI pipeline via GitHub Actions. You can replicate this pipeline locally using the `fusion` tool.

| Stage | Command | Purpose |
|-------|---------|---------|
| **Codegen** | `python -m tools.fusion.main --stage codegen` | Validates IDLs and generates all bindings |
| **Build** | `python -m tools.fusion.main --stage build` | Compiles Rust, C++, and TS on the current host |
| **Test** | `python -m tools.fusion.main --stage test` | Runs unit tests for all runtimes |
| **Demos** | `python -m tools.fusion.main --stage demos` | Executes cross-language integration scenarios |
| **Coverage**| `python -m tools.fusion.main --stage coverage` | Generates aggregated coverage reports |

### Virtual Network (VNet) Testing
On Linux (including WSL2), the `fusion` tool can perform advanced network simulation using network namespaces:

```bash
# Setup virtual interfaces and bridges
sudo bash tools/fusion/scripts/setup_vnet.sh

# Run tests within namespaces
sudo -E python3 -m tools.fusion.main --stage test --pass-filter vnet

# Teardown
sudo bash tools/fusion/scripts/teardown_vnet.sh
```

---

## Logging

All runtimes use a pluggable logger interface for DLT compatibility:

| Language | Interface | Default |
|----------|-----------|---------|
| Rust | `FusionLogger` trait | `ConsoleLogger` |
| Python | `ILogger` base class | `ConsoleLogger` |
| C++ | `ILogger` abstract class | `ConsoleLogger` |
| JS/TS | `ILogger` interface | `ConsoleLogger` |

---

## Running Examples

The `examples/` directory contains four categories:

| Directory | Purpose | Docs |
|-----------|---------|------|
| `sd_demos/` | Service Discovery isolation | [Examples README](../examples/README.md#1-raw-service-discovery) |
| `simple_no_sd/` | Raw wire protocol (no Service Discovery) | [Examples README](../examples/README.md#2-simple-no-sd) |
| `integrated_apps/` | Full runtime with RPC | [Examples README](../examples/README.md#3-integrated-apps) |
| `automotive_pubsub/` | Pub/Sub event pattern | [Examples README](../examples/README.md#4-automotive-pub-sub) |
| `someipy_demo/` | Interop with 3rd party stacks | [Examples README](../examples/README.md#5-external-interop) |

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
