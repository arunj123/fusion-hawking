---
description: Coding Rules
---

## Configuration and Hardcoding
- **No Hardcoded Fallbacks**: NO hardcoded fallbacks for interface IPs, multicast addresses, or ports. If configuration is missing or invalid, the application MUST log a clear error and exit immediately.
- **Strict Config Validation**: Configurations must be validated at the earliest possible stage (e.g., by the fusion tool or at runtime initialization). If a required network feature (like IPv6) is missing from the environment or configuration, the build or test suite MUST fail with a descriptive message.
- **Legacy Code Removal**: No deprecated or legacy interfaces, constructors, or transitional implementations are allowed. All code must follow the latest modular architecture.
- **Fail on missing config**: If a required configuration value is missing, the system should raise an explicit error or log a failure rather than falling back to a "safe" default like `127.0.0.1` or `localhost`.
- **Patching responsibility**: The automation toolkit (`fusion`) and user configuration are responsible for ensuring all necessary values are present and correct.
- **ID and IP Provenance**: All IDs and IPs shall always be derived from IDL or configuration files. The only exception is for interoperability tests with external SOME/IP implementations where static values might be necessary for coordination.
- **ID Management**: Follow the rules defined in [ID_MANAGEMENT_RULES.md](fusion-hawking/docs/ID_MANAGEMENT_RULES.md) for all updates to service, instance, and event identifiers.

## Demos and Documentation
- **Consistency**: For all demos, ensure that the accompanying documentation and PUML diagrams are added or updated whenever demo implementation changes. Demos are the primary learning resource for users.

## Platform Specifics
- **Binary detection**: On Windows, always favor `.exe` binaries and exclude build artifacts from WSL (Linux) environments to avoid execution errors.
- **Header compatibility**: Use appropriate conditional compilation (`#ifdef _WIN32`) for networking headers and library linking on Windows.

## Environment Adaptation
- **No runtime environment detection**: Runtime code MUST NOT detect the OS, check for interface availability, or adapt its binding behavior at runtime. All environment-specific adaptation is the sole responsibility of the `fusion` tool via `config.json` patching.
- **Fusion tool responsibility**: The `fusion` tool MUST detect the environment (OS, available interfaces, multicast support, IPv6 availability, CI/WSL constraints) and prepare the configuration before any runtime is started.
- **Capability logging**: Every test run MUST log the detected environment capabilities (OS, interfaces, multicast status, IPv6 status) to the run report. Tests requiring unavailable capabilities MUST be explicitly skipped with a logged reason, never silently failed or hung.
- **Config is the single source of truth**: If a platform requires `0.0.0.0` or `INADDR_ANY` for bind compatibility, this must be set in `config.json` by the fusion tool — never hardcoded in runtime source code.