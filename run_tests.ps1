# Run Tests Script
# Python Venv Setup
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv .venv
}

# Activate Venv
if (Test-Path ".venv/Scripts/Activate.ps1") {
    . .venv/Scripts/Activate.ps1
}

Write-Host "Installing requirements..."
pip install -r requirements.txt

Write-Host "Generating bindings..."
python -m tools.codegen.main examples/interface.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Code Generation Failed"
    exit 1
}

Write-Host "Running Rust Unit Tests..."
cargo test
if ($LASTEXITCODE -ne 0) {
    Write-Error "Rust Tests Failed"
    exit 1
}

Write-Host "Running Python Unit Tests..."
python -m unittest discover tests
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python Tests Failed"
    exit 1
}

Write-Host "Running C++ Unit Tests..."

# C++ Tests using CMake
Write-Host "Running C++ Unit Tests (CMake)..."

if (Get-Command "cmake" -ErrorAction SilentlyContinue) {
    if (-not (Test-Path "build")) { mkdir build }
    cd build
    cmake ..
    cmake --build . --config Release
    
    if ($LASTEXITCODE -eq 0) {
        if (Test-Path "Release/cpp_test.exe") {
            ./Release/cpp_test.exe
        } elseif (Test-Path "Debug/cpp_test.exe") {
             ./Debug/cpp_test.exe
        } elseif (Test-Path "cpp_test.exe") {
             ./cpp_test.exe
        } else {
             Write-Error "Could not find compiled cpp_test executable."
             exit 1
        }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Error "C++ Tests Failed"
            exit 1
        }
    } else {
        Write-Error "CMake Build Failed"
        exit 1
    }
    cd ..
} else {
    Write-Warning "CMake not found. Skipping C++ tests."
}

Write-Host "All Tests Passed."
