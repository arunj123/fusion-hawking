## Core Principle
**Separation of Definition and Deployment**
- **Static Identifiers** (What functions exist?) -> **IDL**
- **Deployment Identifiers** (Where are they running?) -> **Configuration**

## 1. IDL (Interface Definition Language) requirements
The IDL is the single source of truth for the *interface contract*. It must contain:
- **Service ID**: Unique 16-bit identifier for the service class.
- **Major Version**: Breaking change version.
- **Minor Version**: Non-breaking change version.
- **Methods**: Function signatures and their implicit/explicit IDs.
- **Event IDs**: Unique identifiers for events.
- **Event Group IDs**: Grouping for events.
- **Data Types**: Structs, fields, and their types.

## 2. Configuration requirements
The Configuration manages the *instantiation* of the interface. It must contain:
- **Instance ID**: Unique 16-bit identifier for a specific instance of the service.
- **Network Endpoints**: IP addresses (Unicast/Multicast), Ports, Transports (UDP/TCP).
- **Interface Bindings**: Which network interface to use.

*Config Format:* See the config JSON schema in `tools/fusion/config_schema.json` for the authoritative structure. Do not use inline examples — they drift from the real format.

## 3. Application Code Rules
- **No Hardcoded IDs**: Application code must NOT contain magic numbers like `0x1234` or `4660`.
- **Use Generated Constants**: Code must import generated constants from the IDL-derived code (e.g., `MyService.SERVICE_ID`).
- **Load Instance from Config**: Code must load the specific instance configuration to know *which* instance ID to use.

## 4. IP Address Rules
- **No Hardcoded IPs**: Core runtime code must not have hardcoded IPs like `127.0.0.1` or `::1` as defaults. Fallbacks are strictly forbidden.
- **Endpoint-Centric**: Interface IPs are defined ONLY in the `endpoints` section. Instances must refer to these via `providing` services.
- **No Instance IPs**: The `ip` and `ip_v6` fields in the `instances` block are deprecated and must be removed.
- **SD-Centric Discovery**: If Service Discovery (SD) is enabled for an instance, `required` services should NOT specify a static `endpoint`. The runtime must wait for discovery.
- **No Bind Exceptions**: Runtimes MUST bind exclusively to the IP specified in the `endpoints` configuration. Binding to `0.0.0.0` (INADDR_ANY), `127.0.0.1`, or `::` is forbidden in runtime code. If a specific platform (e.g., Windows) requires wildcard binding for compatibility, the `fusion` tool MUST detect this environment and patch the `config.json` endpoints accordingly before launching the runtime.

## 5. Versioning
- **Major Versioning**: Different major versions of the same Service ID are treated as distinct services by the runtime.
  - Runtime key: `(ServiceId, MajorVersion)`.
  - Clients must specify `major_version` (default 1) in `config.json` `required` section.
- **Minor Versioning**: Handled via SOME/IP SD backward compatibility check (Min Version), but currently less strictly enforced by Python runtime.
   
## 6. Protocol Compliance
All runtimes and tools MUST strictly adhere to the **AUTOSAR R22-11** SOME/IP and SOME/IP-SD specifications.
- **SD Option Lengths**: MUST be 9 bytes for IPv4 Endpoint/Multicast and 21 bytes for IPv6 Endpoint/Multicast (Length field excludes Type and Length fields themselves).
- **Golden Byte Tests**: Any change to SD packet construction MUST be verified against the cross-language Golden Byte test suite.
