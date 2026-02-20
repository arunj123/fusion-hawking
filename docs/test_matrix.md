# Integration Test Matrix

> **See Also:** [User Guide](user_guide.md) | [Architecture](architecture.md) | [Design Doc](design_and_requirements.md)

This document tracks test coverage and cross-language interoperability status against **AUTOSAR R22-11**.

---

## Test Coverage by Component

| Component | Test File | Type | Status |
|-----------|-----------|------|--------|
| **Rust Runtime** | `tests/transport_test.rs` | Unit | ✅ |
| | `tests/sd_test.rs` | Unit | ✅ |
| | `cargo test` | Integration | ✅ |
| **Python Runtime** | `tests/` (pytest) | Unit | ✅ |
| | Cross-lang serialization | Integration | ✅ |
| **C++ Runtime** | `examples/cpp_test/main.cpp` | Unit | ✅ |
| | Serialization roundtrip | Integration | ✅ |
| **JS/TS Runtime** | `src/js/tests/` (node --test) | Unit | ✅ |
| | Serialization roundtrip | Integration | ✅ |
| **Negative Tests** | `tests/test_negative.py` | Integration | ✅ |


---

## Cross-Language Interoperability

| Scenario | Provider | Consumer | Status |
|----------|----------|----------|--------|
| SOME/IP Serialization | Rust | Python | ✅ |
| SOME/IP Serialization | Python | Rust | ✅ |
| SOME/IP Serialization | C++ | Rust | ✅ |
| SOME/IP Serialization | JS/TS | Python | ✅ |
| Service Discovery | All | All | ✅ |
| Request/Response RPC | Rust | Python | ✅ |
| Request/Response RPC | Python | C++ | ✅ |
| Request/Response RPC | JS/TS | Rust | ✅ |
| Request/Response RPC | C++ | JS/TS | ✅ |
| Event Subscription | Rust | Python | ✅ |
| Event Subscription | JS/TS | Rust | ✅ |
| Event Subscription | C++ | JS/TS | ✅ |
| **External Interop** | | | |
| someipy (Python) | Fusion Python | someipyd | ✅ |
| someipy (Python) | Fusion C++ | someipyd | ✅ |
| someipy (Python) | Fusion JS/TS | someipyd | ✅ |


> **Data Flow Diagram:** See [Architecture - Request/Response](architecture.md#requestresponse-data-flow)

---

## Feature Coverage

| Feature | Rust | Python | C++ | JS/TS | Notes |
|---------|------|--------|-----|-------|-------|
| UDP Transport | ✅ | ✅ | ✅ | ✅ | |
| TCP Transport | ✅ | ✅ | ✅ | ✅ | Rust/Py/C++ verified |
| Service Discovery | ✅ | ✅ | ✅ | ✅ | Multi-interface |
| IPv4 | ✅ | ✅ | ✅ | ✅ | |
| IPv6 | ✅ | ✅ | ✅ | ✅ | |
| Configuration | ✅ | ✅ | ✅ | ✅ | Interface-centric |
| Logging | ✅ | ✅ | ✅ | ✅ | DLT-ready |
| Events (Pub/Sub) | ✅ | ✅ | ✅ | ✅ | |
| SOME/IP-TP | ✅ | ✅ | ✅ | ✅ | Large payload support |
| Packet Dump | ✅ | ✅ | ✅ | ✅ | Runtime diagnostics |


> **Feature Details:** See [Design Doc - IPv6 Support](design_and_requirements.md#4-ipv6-support)

---

## Running Tests

### Automated (Recommended)

```powershell
# Windows - Full automation with dashboard
.\fusion.bat

# Linux/WSL
./fusion.sh
```

Dashboard shows live test results at http://localhost:8000.

### Manual Verification

```powershell
# Rust
cargo test

# Python
pytest tests/

# C++
cmake --build build --config Release
.\build\Release\cpp_test.exe

# JS/TS
cd src/js && npm test

```

---

## Coverage Reports

After a test run, coverage reports are available in `logs/latest/coverage/`:

| Language | Report Path | Tool |
|----------|-------------|------|
| Rust | `coverage/rust/index.html` | `cargo-llvm-cov` |
| Python | `coverage/python/index.html` | `coverage.py` |
| C++ (Windows) | `coverage/cpp/index.html` | `OpenCppCoverage` |
| C++ (Linux) | `coverage/cpp/index.html` | `lcov` / `genhtml` |
| JS/TS | `coverage/js/index.html` | `c8` |


> **CI/CD Pipeline:** See [Architecture - Automation Pipeline](architecture.md#automation--cicd-pipeline)

---

## Verification Checklist

- [x] All unit tests pass (`cargo test`, `pytest`, `npm test`)
- [x] Cross-language RPC verified (Rust ↔ Python ↔ C++ ↔ JS/TS)
- [x] Service Discovery works on multicast `224.0.0.1:30490`
- [x] Events delivered to all subscribers (Automotive Pub-Sub Demo)
- [x] Coverage reports generated for all languages (including JS/TS)
