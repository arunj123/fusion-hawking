# Design & Requirements: Configuration-Driven SOME/IP Stack

## 1. Objective
To introduce a configuration layer that decouples Service IDs, Instance IDs, Ports, and IP addresses from the application code. This allows flexible deployment scenarios without recompilation and solves persistent "hardcoded port" mismatch issues.

## 2. JSON Configuration Schema
The system will use a single JSON file to define the topology of the distributed system.

### Structure
```json
{
  "instances": {
    "app_instance_name": {
      "ip": "127.0.0.1",
      "providing": {
        "service_alias_name": {
          "service_id": 0x1234,
          "instance_id": 1,
          "major_version": 1,
          "minor_version": 0,
          "port": 30509,
          "protocol": "udp",
          "multicast": {
             "ip": "224.0.0.1",
             "port": 30490
          }
        }
      },
      "required": {
        "client_alias_name": {
          "service_id": 0x5678,
          "instance_id": 1,
          "major_version": 1,
           // Optional: Static routing if SD is bypassed
          "static_ip": "127.0.0.1", 
          "static_port": 30510
        }
      }
    }
  }
}
```

## 3. Runtime API Changes

All runtimes (C++, Rust, Python) must support initializing from this configuration.

### 3.1 C++ API
**Current:**
```cpp
SomeIpRuntime rt(30509);
```
**New:**
```cpp
SomeIpRuntime rt("config.json", "cpp-app-instance");
```
**Usage:**
```cpp
// Offering
rt.offer_service("math-service", my_math_impl);

// Consuming
auto client = rt.create_client<MathServiceClient>("math-client");
```

### 3.2 Python API
**Current:**
```python
rt = SomeIpRuntime(30510)
```
**New:**
```python
rt = SomeIpRuntime("config.json", "python-app-instance")
```
**Usage:**
```python
rt.offer_service("string-service", StringImpl())
client = rt.get_client("math-client", MathClient)
```

### 3.3 Rust API
**Current:**
```rust
let rt = SomeIpRuntime::new(30509);
```
**New:**
```rust
let rt = SomeIpRuntime::load("config.json", "rust-app-instance");
```
**Usage:**
```rust
rt.offer_service("math-service", Box::new(math_service));
let client = rt.get_client::<StringServiceClient>("string-client");
```

## 4. Implementation Details

### JSON Parsing
- **Python**: Built-in `json` module.
- **Rust**: `serde` + `serde_json`.
- **C++**: Minimally invasive JSON parser. For this playground, a simple header-only library (like `nlohmann/json` or a tiny custom parser for this specific schema) is preferred. Given the constraints, we might use a very simple regex-based parser or `picojson` if available, or just implement a basic parser for the specific known structure to avoid heavy dependencies on Windows. *Decision*: Will attempt to use a simple custom parser in `json_parser.h` to keep it dependency-free.

### Service Discovery Integration
- The Runtime will now use the Configured IP/Port for its bind address.
- `offer_service` will look up the `service_id` and packing details from the config, not just the generated class.

## 5. Migration Strategy
1. Create `config.json`.
2. Update Runtimes to load config.
3. Update Demos to use config aliases.
## 6. Logging Abstraction (DLT-Ready)

To support future DLT (Diagnostic Log and Trace) integration without adding heavy dependencies now, we will introduce a `Logger` abstraction in all runtimes.

### Rust
- **Trait**: `pub trait FusionLogger { fn log(&self, level: LogLevel, component: &str, msg: &str); }`
- **Default**: `StdOutLogger` (console).
- **Future**: `DltLogger` implementation.

### C++
- **Abstract Class**: `class ILogger { virtual void Log(LogLevel level, const char* comp, const char* msg) = 0; }`
- **Injection**: Passed to `SomeIpRuntime` constructor.

### Python
- **Polymorphism**: Base `Logger` class.
- **Integration**: `SomeIpRuntime(config, logger=MyLogger())`

## 7. IPv6 Support
The configuration schema supports `protocol` specific settings.
```json
"multicast": {
  "ip": "ff14::1", // IPv6 Multicast
  "port": 30490
}
```
- **Socket Creation**: Runtimes must detect IP version from the config string (contains `:`) and open `AF_INET6` sockets accordingly.
- **SD Endpoint Option**: Generator must choose between IPv4 Option (0x04) and IPv6 Option (0x06).

## 8. Concurrency & Async Model
- **Non-blocking IO**: All sockets set to non-blocking.
- **Thread Pool**:
    - **Rust**: Existing `ThreadPool` for handler execution.
    - **C++**: Simple `std::vector<std::thread>` pool for callback execution to avoid blocking the reactor loop.
    - **Python**: `concurrent.futures.ThreadPoolExecutor` for service method calls.
- **Callbacks**:
    - `on_message(service, result)` style for clients.

## 9. Dependency Management
- **Rule**: No OS-level installs required.
- **Rust**: `serde`, `serde_json` (Standard in ecosystem, static link).
- **C++**: `SimpleJson` (Header only, committed to repo). No Boost.
- **Python**: Standard Library `json`, `socket`, `threading`.

## 10. Testing Strategy
- **Unit Tests**: Test configuration loading and parsing in isolation.
- **Integration Matrix**:
    - Python Client -> Rust Server (IPv4)
    - Rust Client -> C++ Server (IPv4)
    - C++ Client -> Python Server (IPv6) @TODO
- **Fault Injection**: Test behavior when config refers to unreachable request.
