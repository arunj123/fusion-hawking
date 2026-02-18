# Fusion Hawking IDL Documentation

> **See Also:** [User Guide](user_guide.md) | [Architecture](architecture.md)

This document describes the Interface Definition Language (IDL) used for cross-language service definitions in Fusion Hawking.

---

## Overview

Services are defined using Python dataclasses with type annotations. The code generator (`tools/codegen`) produces type-safe bindings for Rust, Python, and C++.

```bash
python -m tools.codegen.main examples/integrated_apps/interface.py
```

> **Code Generation Pipeline:** See [Architecture - Code Generation](architecture.md#code-generation-pipeline)

---

## Type System

### Primitives

| IDL Type | Python | Rust | C++ | JS/TS |
|----------|--------|------|-----|-------|
| `int` / `int32` | `int` | `i32` | `int32_t` | `number` |
| `int8` | `int` | `i8` | `int8_t` | `number` |
| `int16` | `int` | `i16` | `int16_t` | `number` |
| `int64` | `int` | `i64` | `int64_t` | `bigint` |
| `uint8` | `int` | `u8` | `uint8_t` | `number` |
| `uint16` | `int` | `u16` | `uint16_t` | `number` |
| `uint32` | `int` | `u32` | `uint32_t` | `number` |
| `uint64` | `int` | `u64` | `uint64_t` | `bigint` |
| `float` / `float32` | `float` | `f32` | `float` | `number` |
| `double` / `float64` | `float` | `f64` | `double` | `number` |
| `bool` | `bool` | `bool` | `bool` | `boolean` |
| `string` / `str` | `str` | `String` | `std::string` | `string` |

### Complex Types

```python
from typing import List

# Nested lists (any depth)
List[int]
List[List[int]]
List[List[List[str]]]

# Custom structs
class Point:
    x: int
    y: int
```

---

## Defining Services

```python
from typing import List

class Point:
    x: int
    y: int

class MapService:
    SERVICE_ID = 0x1000
    
    def get_path(self, start: Point, end: Point) -> List[Point]:
        """Returns a path between two points."""
        pass
    
    def add_waypoint(self, point: Point):
        """Adds a waypoint (fire-and-forget)."""
        pass
```

---

## RPC Behavior

| Return Type | Behavior | Client Waits? |
|-------------|----------|---------------|
| Non-None | **Synchronous** | Yes (blocks until response) |
| `None` | **Fire-and-forget** | No (returns immediately) |

### Example

```python
class ExampleService:
    SERVICE_ID = 0x2000
    
    # Synchronous - client waits for int result
    def compute(self, x: int) -> int:
        pass
    
    # Fire-and-forget - client returns immediately  
    def notify(self, message: str):
        pass
```

---

## Events (Pub/Sub)

Events enable the publish/subscribe pattern for notifications:

```python
class RadarService:
    SERVICE_ID = 0x3000
    
    # Event definition
    @event(id=0x8001, eventgroup_id=1)
    on_detection: List[Detection]
    
    # Methods still work alongside events
    def get_status(self) -> int:
        pass
```

> **Event Flow Diagram:** See [Architecture - Subscription Flow](architecture.md#subscription-flow)

---

## Serialization Details (per AUTOSAR R22-11 [PRS_SOMEIP_00030])

| Element | Format |
|---------|--------|
| Byte Order | Big-endian (Network) |
| Primitives | Fixed-width per type table |
| Lists | 4-byte length prefix (byte count) + items |
| Strings | 4-byte length prefix + UTF-8 bytes |
| Structs | Field-by-field in declaration order |

### Wire Format Example

```
add(a=5, b=3) serialized:
┌────────────────────────────────────┬───────────────┐
│ SOME/IP Header (16 bytes)          │ Payload       │
│ ServiceID=0x1001, MethodID=0x0001  │ 00 00 00 05   │  (a = 5)
│ Length=16, MsgType=REQUEST         │ 00 00 00 03   │  (b = 3)
└────────────────────────────────────┴───────────────┘
```

> **Header Format:** See [Architecture - SOME/IP Message Format](architecture.md#someip-message-format)

---

## Generated Code Structure

After running `codegen`, files are created in `build/generated/{project}/`:

```
build/generated/{project}/
├── rust/
│   ├── math_service.rs      # Server trait + Client struct
│   └── mod.rs
├── python/
│   ├── math_service.py      # Handler base + Client class
│   └── __init__.py
├── cpp/
│   ├── MathService.hpp      # Abstract handler + Client class
│   └── generated.hpp
└── ts/
    ├── MathService.ts       # Typed interface + Client/Server stubs
    └── index.ts
```

> [!NOTE]
> For **JavaScript/TypeScript** projects, it is recommended to copy the contents of `build/generated/{project}/ts/` to a local `src/generated/` directory within your app to ensure reliable module resolution with `NodeNext`.

---

## Next Steps

- **Using generated code:** [User Guide - Runtime API](user_guide.md#runtime-api)
- **Event patterns:** [Examples - Automotive Pub/Sub](../examples/README.md#4-automotive-pub-sub)
- **Testing services:** [Test Matrix](test_matrix.md)
