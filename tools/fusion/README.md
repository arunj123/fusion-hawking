# Fusion Automation Tools (`tools/fusion`)

This package provides the unified build, test, and verification automation for the Fusion Hawking project.

## Architecture

The tool is designed as a modular Python package:

- **`main.py`**: Entry point and orchestration.
- **`toolchains.py`**: Detects required tools (Rust, CMake, Python, OpenCppCoverage).
- **`build.py`**: Handles building Rust/C++ and code generation.
- **`test.py`**: Runs unit tests and the complex integration demos.
- **`coverage.py`**: Orchestrates coverage generation for all languages.
- **`tests/`**: Unit test suites for all languages.
- **`config_validator.py`**: Validates `config.json` against the interface-centric schema.
- **`server.py`**: A simple background HTTP server for the live dashboard.
- **`report.py`**: Generates HTML reports and manages the `logs/` directory.

## Usage

### Direct Usage
```bash
# Recommended - run everything
python -m tools.fusion.main

# Granular execution
python -m tools.fusion.main --stage build --target rust
python -m tools.fusion.main --stage test --target python
python -m tools.fusion.main --stage demos --demo integrated
```

### Options
- `--packet-dump`: Enable protocol-level packet dumping for all runtimes.
- `--clean`: Clean build 1and log directories before starting.
- `--stage <name>`: Run a specific stage (`toolchain`, `codegen`, `build`, `test`, `demos`).
- `--target <lang>`: Limit stage to a specific language (`rust`, `python`, `cpp`, `js`).
- `--skip-coverage`: Skip coverage generation.
- `--server`: Enable/Disable the live dashboard server (Default: Enabled).

## Logs

All artifacts are stored in `logs/<timestamp>`. A symlink `logs/latest` always points to the most recent run.

- `logs/latest/index.html`: The main dashboard.
- `logs/latest/coverage/`: Coverage reports.
- `logs/latest/raw_logs/`: Raw stdout/stderr captures.
