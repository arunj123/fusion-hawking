# Integration Test Matrix

## Test Coverage by Component

| Component          | Test File                  | Test Type    | Status |
|--------------------|----------------------------|--------------|--------|
| **Rust Runtime**   | `tests/transport_test.rs`  | Unit         | ✅     |
|                    | `tests/sd_test.rs`         | Unit         | ✅     |
|                    | `cargo test`               | Integration  | ✅     |
| **Python Runtime** | `tests/` (pytest)          | Unit         | ✅     |
|                    | Cross-lang serialization   | Integration  | ✅     |
| **C++ Runtime**    | `examples/cpp_test/main.cpp` | Unit       | ✅     |
|                    | Serialization roundtrip    | Integration  | ✅     |

## Cross-Language Interoperability

| Scenario                     | Provider | Consumer | Status |
|------------------------------|----------|----------|--------|
| SOME/IP Serialization        | Rust     | Python   | ✅     |
| SOME/IP Serialization        | Python   | Rust     | ✅     |
| SOME/IP Serialization        | C++      | Rust     | ✅     |
| Service Discovery            | All      | All      | ✅     |
| Request/Response             | Rust     | Python   | ✅     |

## Feature Coverage

| Feature               | Rust | Python | C++ |
|-----------------------|------|--------|-----|
| UDP Transport         | ✅   | ✅     | ✅  |
| TCP Transport         | ✅   | ⬜     | ⬜  |
| Service Discovery     | ✅   | ✅     | ⬜  |
| IPv4                  | ✅   | ✅     | ✅  |
| IPv6                  | ✅   | ✅     | ✅  |
| Configuration (JSON)  | ✅   | ✅     | ✅  |
| Logging               | ✅   | ✅     | ✅  |

## Running Tests

```powershell
# Windows
.\run_tests.ps1

# Linux/WSL
./run_tests.sh
```

## Verification Commands

```powershell
# Rust only
cargo test

# Python only
pytest tests/

# C++ only
cmake --build build --config Release
.\build\Release\cpp_test.exe
```
