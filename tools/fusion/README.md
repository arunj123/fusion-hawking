# Fusion Automation Tools (`tools/fusion`)

This package provides the unified build, test, and verification automation for the Fusion Hawking project.

## Architecture

The tool is designed as a modular Python package:

- **`main.py`**: Entry point and orchestration.
- **`toolchains.py`**: Detects required tools (Rust, CMake, Python, OpenCppCoverage).
- **`build.py`**: Handles building Rust/C++ and code generation.
- **`test.py`**: Runs unit tests and the complex integration demos.
- **`coverage.py`**: Orchestrates coverage generation for all languages.
- **`server.py`**: A simple background HTTP server for the live dashboard.
- **`report.py`**: Generates HTML reports and manages the `logs/` directory.

## Usage

### Direct Usage
```bash
python -m tools.fusion.main [options]
```

### Options
- `--skip-demos`: Skip the integration demo suite (faster).
- `--skip-coverage`: Skip coverage generation.
- `--server`: Enable/Disable the live dashboard server (Default: Enabled).

## Logs

All artifacts are stored in `logs/<timestamp>`. A symlink `logs/latest` always points to the most recent run.

- `logs/latest/index.html`: The main dashboard.
- `logs/latest/coverage/`: Coverage reports.
- `logs/latest/raw_logs/`: Raw stdout/stderr captures.
