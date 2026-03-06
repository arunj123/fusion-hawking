## Configuration and Hardcoding
- **No Hardcoded Fallbacks**: NO hardcoded fallbacks for interface IPs, multicast addresses, or ports. If configuration is missing or invalid, the application MUST log a clear error and exit immediately.
- **Strict Config Validation**: Configurations must be validated at the earliest possible stage (e.g., by the fusion tool or at runtime initialization). If a required network feature (like IPv6) is missing from the environment or configuration, the build or test suite MUST fail with a descriptive message.
- **Legacy Code Removal**: No deprecated or legacy interfaces, constructors, or transitional implementations are allowed. All code must follow the latest modular architecture.
- **Fail on missing config**: If a required configuration value is missing, the system should raise an explicit error or log a failure rather than falling back to a "safe" default like `127.0.0.1` or `localhost`.
- **Patching responsibility**: The automation toolkit (`fusion`) and user configuration are responsible for ensuring all necessary values are present and correct.
- **ID and IP Provenance**: All IDs and IPs shall always be derived from IDL or configuration files. The only exception is for interoperability tests with external SOME/IP implementations where static values might be necessary for coordination.

## Demos and Documentation
- **Consistency**: For all demos, ensure that the accompanying documentation and PUML diagrams are added or updated whenever demo implementation changes. Demos are the primary learning resource for users.
- **Maintain Documentation**: Whenever any changes are made to the codebase, the relevant documentation, including diagrams, MUST be updated to reflect the new state. This ensures that the documentation is always in sync with the current implementation.

## Platform Specifics
- **Binary detection**: On Windows, always favor `.exe` binaries and exclude build artifacts from WSL (Linux) environments to avoid execution errors.
- **Header compatibility**: Use appropriate conditional compilation (`#ifdef _WIN32`) for networking headers and library linking on Windows.

## Environment Adaptation
- **No runtime environment detection**: Runtime code MUST NOT detect the OS, check for interface availability, or adapt its binding behavior at runtime. All environment-specific adaptation is the sole responsibility of the `fusion` tool via `config.json` patching.
- **Fusion tool responsibility**: The `fusion` tool MUST detect the environment (OS, available interfaces, multicast support, IPv6 availability, CI/WSL constraints) and prepare the configuration before any runtime is started.
- **Capability logging**: Every test run MUST log the detected environment capabilities (OS, interfaces, multicast status, IPv6 status) to the run report. Tests requiring unavailable capabilities MUST be explicitly skipped with a logged reason, never silently failed or hung.
- **Config is the single source of truth**: If a platform requires `0.0.0.0` or `INADDR_ANY` for bind compatibility, this must be set in `config.json` by the fusion tool — never hardcoded in runtime source code.

## Cross-Language Consistency
- **Identical Behavior**: Whenever possible, the behavior across all four implementations (C++, Rust, Javascript, and Python) MUST be identical. This includes packet serialization/deserialization, error handling, state management, and edge-case behavior. Any deviation must be explicitly justified and documented.
- **Golden Byte Tests**: Rely on cross-language integration tests and Golden Byte test suites to verify that the byte-level protocol implementation is consistent across all languages.

## Language-Specific Best Practices

### Python
- Use type hints (`typing`) extensively to improve readability and catch logic errors early.
- Favor `asyncio` for scalable network operations and I/O-bound tasks.
- Keep the `__init__.py` clean; avoid complex logic during import time.

### C++
- Prefer modern C++ (C++14/17/20) features: smart pointers (`std::unique_ptr`, `std::shared_ptr`) over raw pointers, and `constexpr` for compile-time constants.
- Avoid manual memory management and `new`/`delete` keywords.
- Use explicit RAII (Resource Acquisition Is Initialization) semantics for handling sockets and file descriptors.

### Rust
- Leverage Rust's borrow checker and strong type system to guarantee memory safety.
- Use `Result` and `Option` types instead of panicking, unless recovering from the error is impossible.
- Write unit tests alongside the implementation (e.g., `#[cfg(test)]` modules at the bottom of the file).

### JavaScript / TypeScript
- Always prefer TypeScript over vanilla JavaScript for strict type checking.
- Use modern ES6+ features (e.g., arrow functions, destructuring, `async`/`await`).
- Do not use `any` unless absolutely necessary; define strict interfaces for all network structures and events.
- Rely on native Node.js/browser APIs or well-maintained libraries for networking, avoiding outdated synchronous calls.
