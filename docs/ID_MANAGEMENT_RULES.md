# ID and Configuration Rules

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

*Example IDL:*
```python
class MyService:
    SERVICE_ID = 4660
    MAJOR_VERSION = 1
    MINOR_VERSION = 0
```

## 2. Configuration requirements
The Configuration manages the *instantiation* of the interface. It must contain:
- **Instance ID**: Unique 16-bit identifier for a specific instance of the service.
- **Network Endpoints**: IP addresses (Unicast/Multicast), Ports, Transports (UDP/TCP).
- **Interface Bindings**: Which network interface to use.

*Example Config:*
```json
// config.json
{
  "instances": {
    "my_service_instance": {
      "service_id": 4660, 
      "instance_id": 1,   
      "endpoint": "my_endpoint"
    }
  }
}
```

## 3. Application Code Rules
- **No Hardcoded IDs**: Application code must NOT contain magic numbers like `0x1234` or `4660`.
- **Use Generated Constants**: Code must import generated constants from the IDL-derived code (e.g., `MyService.SERVICE_ID`).
- **Load Instance from Config**: Code must load the specific instance configuration to know *which* instance ID to use.

## 4. IP Address Rules
- **No Hardcoded IPs**: Core runtime code must not have hardcoded IPs like `127.0.0.1` or `224.224.224.245` as defaults if they can be avoided.
- **Bind Exception**: For *server listening sockets*, binding to `0.0.0.0` (INADDR_ANY) is permitted if required for OS compatibility (e.g., Windows Multicast), but the *advertised* IP in Service Discovery must be the specific configured interface IP.

## 5. Tooling Support

### 5.1 ID Manager (`tools/id_manager`)
- Scans `src/` and `examples/` for `SERVICE_ID` constant definitions.
- Detects duplicate Service IDs across the codebase.
- Can be used to find the next available ID.

### 5.2 Config Validator (`tools/fusion/config_validator.py`)
- Runs during `fusion` build (codegen stage).
- Validates `config.json` files for:
  - Schema correctness.
  - Endpoint reachability (IP validity).
  - **Conflict Detection**: Ensures no two instances provide the same `(Service ID, Instance ID, Major Version)`.

## 6. Versioning
- **Major Versioning**: Different major versions of the same Service ID are treated as distinct services by the runtime.
  - Runtime key: `(ServiceId, MajorVersion)`.
  - Clients must specify `major_version` (default 1) in `config.json` `required` section.
- **Minor Versioning**: Handled via SOME/IP SD backward compatibility check (Min Version), but currently less strictly enforced by Python runtime.
   
## 7. Protocol Compliance
All runtimes and tools MUST strictly adhere to the project's interpretation of the SOME/IP and SOME/IP-SD specifications.
- **Reference Document**: [SOMEIP_SPEC_COMPLIANCE.md](docs/SOMEIP_SPEC_COMPLIANCE.md)
- **SD Option Lengths**: MUST be 9 bytes for IPv4 Endpoint/Multicast and 21 bytes for IPv6 Endpoint/Multicast (Length field excludes Type and Length fields themselves).
- **Golden Byte Tests**: Any change to SD packet construction MUST be verified against the cross-language Golden Byte test suite.
