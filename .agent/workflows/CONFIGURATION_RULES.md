---
description: Configuration Rules
---

This document outlines the strict network binding and ID management rules for Fusion Hawking runtimes (Python, C++, Rust, JS).

## Network Binding Rules

1.  **Strict Binding**: Runtimes MUST bind only to the instance IP (or assigned endpoint IP) configured in the `config.json`.
2.  **No Fallbacks**: Runtimes MUST NOT fall back to `0.0.0.0` or loopback (`127.0.0.1` / `::1`) if it's not explicitly requested in the configuration.
3.  **Interface Requirement**: Every network endpoint MUST specify a physical or virtual interface (e.g., `eth0`, `lo`, `Wi-Fi`) to ensure stable multicast routing.
4.  **Shared Endpoints**: Multiple services MAY bind to the same IP/Port/Protocol combination if supported by the runtime (e.g., Python `SomeIpRuntime`). Routing is handled by the runtime dispatcher.

## ID Management

1.  **Service IDs**: Must be unique within the system according to `ID_MANAGEMENT_RULES.md`.
2.  **Instance IDs**: Used to differentiate between multiple instances of the same service type.
3.  **Endpoint Names**: Must be unique globally in the `endpoints` section of the configuration.

## Service Discovery (SD)

1.  **Dual-Stack**: SD should be configured for both IPv4 and IPv6 if the system supports it.
2.  **Multicast Interfaces**: SD multicast MUST bind to the same interface as the provided services to ensure advertisements reach the correct network segment.
3.  **No Inferred IPs**: No runtime may infer or default bind IPs. All bind addresses MUST be explicitly present in the `endpoints` section of `config.json`. If a value is missing, the runtime MUST fail with a descriptive error. The `fusion` tool is responsible for ensuring all required values are populated before launch.

## Environment Detection and Config Patching

The `fusion` tool MUST detect environment capabilities and patch `config.json` accordingly. Runtimes never perform environment detection themselves.

1.  **Capability Detection**: The tool detects OS, available interfaces, multicast support, IPv6 availability, and WSL/CI constraints.
2.  **Config Patching**: Based on detected capabilities, the tool patches endpoint IPs, interface names, and SD multicast addresses in `config.json` before any runtime is launched.
3.  **Capability Logging**: All detected environment capabilities, patched values, and skipped tests MUST be logged to the run report for traceability.
4.  **Test Selection**: Tests requiring specific capabilities (e.g., multicast, veth namespaces) are selected or skipped based on the detected environment. No test should silently fail due to missing capabilities.
