# Fusion-Hawking SOME/IP User Guide

## Overview
Fusion-Hawking is a pure SOME/IP stack implementation supporting Rust, Python, and C++ with zero external dependencies.

## Quick Start

### 1. Define Services (`examples/interface.py`)
```python
class MathService:
    SERVICE_ID = 0x1001
    def add(a: int, b: int) -> int: ...
```

### 2. Generate Bindings (outputs to `build/generated/`)
```bash
python -m tools.codegen.main examples/interface.py
```

### 3. Run Tests
```powershell
.\run_tests.ps1   # Windows (includes codegen)
```

### 4. Run Demos
```powershell
.\run_demos.ps1   # Includes codegen + build
```

## Configuration (`examples/config.json`)
```json
{
  "instances": {
    "my_instance": {
      "ip": "127.0.0.1",
      "ip_version": 4,
      "providing": { ... },
      "required": { ... }
    }
  }
}
```

### IPv6 Support
Set `"ip_version": 6` in instance config to use IPv6 sockets.

## Logging
All runtimes use a pluggable logger interface:
- **Rust**: `FusionLogger` trait
- **Python**: `Logger` base class  
- **C++**: `ILogger` interface

## Architecture
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Rust App  │     │  Python App │     │   C++ App   │
├─────────────┤     ├─────────────┤     ├─────────────┤
│  Runtime    │◄───►│   Runtime   │◄───►│   Runtime   │
├─────────────┤     ├─────────────┤     ├─────────────┤
│  Transport  │     │  Transport  │     │  Transport  │
│  (UDP/TCP)  │     │  (socket)   │     │  (socket)   │
└─────────────┘     └─────────────┘     └─────────────┘
        ▲                 ▲                   ▲
        └────────Service Discovery────────────┘
                   (224.0.0.1:30490)
```

## API Reference

### Rust
```rust
let rt = SomeIpRuntime::load("config.json", "instance_name");
rt.offer_service("alias", Box::new(MyServiceImpl));
rt.run();
```

### Python
```python
rt = SomeIpRuntime("config.json", "instance_name")
rt.offer_service("alias", MyServiceStub())
```

### C++
```cpp
SomeIpRuntime rt("config.json", "instance_name");
rt.offer_service("alias", &my_service_impl);
while(true) { /* event loop */ }
```
