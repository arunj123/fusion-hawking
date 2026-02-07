# Design & Requirements

> **See Also:** [Architecture](architecture.md) | [User Guide](user_guide.md) | [IDL Reference](IDL.md)

This document captures the design decisions and technical requirements for the Fusion Hawking SOME/IP stack.

---

## 1. Objective

Introduce a **configuration-driven architecture** that decouples Service IDs, Instance IDs, Ports, and IP addresses from application code. This enables:
- Flexible deployment without recompilation
- Consistent topology across all language runtimes
- Resolution of "hardcoded port" mismatch issues

---

## 2. JSON Configuration Schema

A single `config.json` defines the distributed system topology. All runtimes load and interpret this identically.

```json
{
  "instances": {
    "app_instance_name": {
      "ip": "127.0.0.1",
      "providing": {
        "service_alias": {
          "service_id": "0x1234",
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
        "client_alias": {
          "service_id": "0x5678",
          "instance_id": 1,
          "major_version": 1,
          "static_ip": "127.0.0.1",
          "static_port": 30510
        }
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `providing` | Services this instance offers |
| `required` | Services this instance consumes |
| `static_ip/port` | Optional bypass for Service Discovery |
| `multicast` | SD announcement group (default: `224.0.0.1:30490`) |

> **Deployment Diagram:** See [Architecture - Deployment Topology](architecture.md#deployment-topology)

---

## 3. Logging Abstraction (DLT-Ready)

All runtimes implement a pluggable logger for future DLT (Diagnostic Log and Trace) integration:

| Language | Interface | Injection Point |
|----------|-----------|-----------------|
| Rust | `trait FusionLogger` | Via builder or `with_logger()` |
| Python | `class ILogger` | Constructor parameter |
| C++ | `class ILogger` | Constructor parameter |

```rust
// Rust trait
pub trait FusionLogger: Send + Sync {
    fn log(&self, level: LogLevel, component: &str, msg: &str);
}
```

```cpp
// C++ interface
class ILogger {
public:
    virtual void Log(LogLevel level, const char* comp, const char* msg) = 0;
};
```

---

## 4. IPv6 Support

Configuration auto-detects IP version from address format:

```json
"multicast": {
  "ip": "ff14::1",
  "port": 30490
}
```

**Implementation:**
- Socket creation uses `AF_INET6` when address contains `:`
- SD Endpoint Option selects IPv4 (0x04) or IPv6 (0x06) accordingly

> **Feature Matrix:** See [Test Matrix](test_matrix.md#feature-coverage) for IPv6 support status.

---

## 5. Concurrency Model

![Concurrency Model](images/concurrency_model.png)

<details>
<summary>View PlantUML Source</summary>

[concurrency_model.puml](diagrams/concurrency_model.puml)
</details>

**Key Principles:**
- All sockets set to non-blocking
- Handlers execute in thread pool (don't block reactor)
- Callbacks follow `on_message(service, result)` pattern

---

## 6. Dependency Management

| Language | Dependencies | Notes |
|----------|--------------|-------|
| Rust | `serde`, `serde_json` | Standard ecosystem, statically linked |
| C++ | None | Custom header-only JSON parser |
| Python | None | Standard library only (`json`, `socket`, `threading`) |

**Rule:** No OS-level package installs required.

---

## 7. Testing Strategy

### Unit Tests
- Configuration loading and parsing
- Codec serialization roundtrip
- SD state machine transitions

### Integration Matrix

| Client | Server | Protocol | Status |
|--------|--------|----------|--------|
| Python | Rust | IPv4 | ✅ |
| Rust | C++ | IPv4 | ✅ |
| C++ | Python | IPv6 | ✅ |

> **Full Matrix:** See [Test Matrix](test_matrix.md)

### Fault Injection
- Unreachable config targets
- Malformed packets
- TTL expiry

---

## 8. Migration Path

For projects adopting Fusion Hawking:

1. **Create `config.json`** with your topology
2. **Update runtime initialization** to use config:
   ```rust
   // Before
   let rt = SomeIpRuntime::new(30509);
   // After  
   let rt = SomeIpRuntime::load("config.json", "my-instance");
   ```
3. **Replace hardcoded IDs** with config aliases:
   ```rust
   rt.offer_service("math-service", handler);  // Uses config lookup
   ```

> **API Examples:** See [User Guide - Runtime API](user_guide.md#runtime-api)

---

## References

- [Architecture Document](architecture.md) - Visual diagrams and layer details
- [User Guide](user_guide.md) - Day-to-day usage
- [IDL Documentation](IDL.md) - Type system and code generation
- [Test Matrix](test_matrix.md) - Coverage and verification status
