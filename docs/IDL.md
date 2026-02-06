# Fusion Hawking IDL Documentation

This document describes the Interface Definition Language (IDL) used in the Fusion Hawking project for cross-language communication.

## Type System

The IDL supports a variety of primitive types and recursive structures.

### Supported Primitives

| IDL Type | Python | Rust | C++ |
| :------- | :----- | :--- | :--- |
| `int` / `int32` | `int` | `i32` | `int32_t` |
| `int8` | `int` | `i8` | `int8_t` |
| `int16` | `int` | `i16` | `int16_t` |
| `int64` | `int` | `i64` | `int64_t` |
| `uint8` | `int` | `u8` | `uint8_t` |
| `uint16` | `int` | `u16` | `uint16_t` |
| `uint32` | `int` | `u32` | `uint32_t` |
| `uint64` | `int` | `u64` | `uint64_t` |
| `float` / `float32` | `float` | `f32` | `float` |
| `double` / `float64` | `float` | `f64` | `double` |
| `bool` | `bool` | `bool` | `bool` |
| `string` / `str` | `str` | `String` | `std::string` |

### Recursive Types

The IDL supports nested lists using the `List[T]` syntax. This can be nested to any depth, e.g., `List[List[int]]`.

## Defining Services

Services are defined using Python classes with type annotations.

### Example

```python
from typing import List

class Point:
    x: int
    y: int

class MapService:
    SERVICE_ID = 0x1000
    
    def get_path(self, start: Point, end: Point) -> List[Point]:
        """Calculates a path between two points."""
        pass

    def add_points(self, points: List[Point]):
        """Adds a list of points to the map."""
        pass
```

## RPC Behavior

### Synchronous RPC
Methods that specify a return type (other than `None`) will result in a **synchronous** call in the generated client. The client will wait for a response from the service or timeout.

### Fire-and-Forget
Methods with a `None` return type are **asynchronous** and "fire-and-forget". The client sends the request and returns immediately without waiting for a result.

## Implementation Details

- **Serialization**: Big-endian (Network Byte Order) is used for all primitive types.
- **Lists**: Lists are prefixed with a 4-byte length field indicating the total byte length of the serialized items.
- **Strings**: Strings are prefixed with a 4-byte length field and encoded as UTF-8.
- **Structs**: Structs are serialized field-by-field in the order they are defined.
- **SOME/IP**: The underlying transport uses SOME/IP headers (16 bytes) with appropriate Service IDs, Method IDs, and Session IDs for request/response matching.
