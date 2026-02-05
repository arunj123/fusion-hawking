# Generate Coverage Reports Script

# 1. Setup Python Coverage
Write-Host "Setting up Python coverage..."
python -m pip install --upgrade pip | Out-Null
pip install -r requirements.txt | Out-Null

# 2. Setup Rust Coverage
Write-Host "Checking for cargo-llvm-cov..."
$hasRustCov = $false
if (Get-Command "cargo-llvm-cov" -ErrorAction SilentlyContinue) {
    $hasRustCov = $true
}
else {
    Write-Host "cargo-llvm-cov not found. Attempting install (compatibility check)..."
    # Try install once, silence output to avoid scary console warnings
    $null = cargo install cargo-llvm-cov --version 0.6.21 2>&1
    if ($LASTEXITCODE -eq 0) { $hasRustCov = $true }
    else { Write-Host "rustc version incompatible with cargo-llvm-cov. Skipping Rust coverage (running standard tests)." -ForegroundColor Yellow }
}

# Create output directory
if (-not (Test-Path "coverage")) { mkdir coverage }

# 3. Run Rust Coverage
if ($hasRustCov) {
    Write-Host "Generating Rust Coverage..."
    # Clean previous data
    cargo llvm-cov clean --workspace
    # Run tests with coverage
    cargo llvm-cov --html --output-dir coverage/rust --ignore-filename-regex "tests|examples|tools"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Rust coverage report generated at coverage/rust/index.html" -ForegroundColor Green
    }
    else {
        Write-Error "Rust coverage generation failed"
    }
}
else {
    Write-Host "Running Rust tests (no coverage)..."
    cargo test
}


# 4. Run C++ Coverage
Write-Host "Checking for OpenCppCoverage..."
if (Get-Command "OpenCppCoverage" -ErrorAction SilentlyContinue) {
    Write-Host "Generating C++ Coverage..."
    $cppTestExe = "build/Release/cpp_test.exe"
    if (-not (Test-Path $cppTestExe)) { $cppTestExe = "build/Debug/cpp_test.exe" }
    
    if (Test-Path $cppTestExe) {
        # Run coverage
        OpenCppCoverage --sources "src\cpp" --export_type html:coverage/cpp -- "$cppTestExe"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "C++ coverage report generated at coverage/cpp/index.html" -ForegroundColor Green
        }
        else {
            Write-Error "C++ coverage generation failed"
        }
    }
    else {
        Write-Warning "C++ test executable not found. Build project first."
    }
}
else {
    Write-Host "OpenCppCoverage not found. Skipping C++ coverage." -ForegroundColor Yellow
    Write-Host "To enable, install from: https://github.com/OpenCppCoverage/OpenCppCoverage/releases"
}

# 5. Run Python Coverage
Write-Host "Generating Python Coverage..."
$env:PYTHONPATH = "src/python;build;build/generated/python"
pytest --cov=src/python --cov-report=html:coverage/python --cov-report=term tests/
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python coverage generation failed"
}
else {
    Write-Host "Python coverage report generated at coverage/python/index.html" -ForegroundColor Green
}

# 5. Summary
Write-Host "`n--- Coverage Reports ---"
if ($hasRustCov) { Write-Host "Rust:   file://$PWD/coverage/rust/index.html" }
else { Write-Host "Rust:   (Coverage skipped, standard tests run)" }
if (Test-Path "coverage/cpp/index.html") { Write-Host "C++:    file://$PWD/coverage/cpp/index.html" }
else { Write-Host "C++:    (Skipped - OpenCppCoverage not installed)" }
Write-Host "Python: file://$PWD/coverage/python/index.html"
exit 0
