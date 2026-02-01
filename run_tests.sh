#!/bin/bash
set -e

echo "Running tests in $(pwd)..."

# 1. Python Venv Setup
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing requirements..."
pip install -r requirements.txt

# 2. Rust Tests
echo "Running Rust Unit Tests..."
cargo test

# 3. Python Tests
echo "Running Python Unit Tests..."
python3 -m unittest discover tests

# 4. C++ Tests (CMake)
echo "Running C++ Unit Tests (CMake)..."
if command -v cmake >/dev/null 2>&1; then
    mkdir -p build
    cd build
    cmake ..
    cmake --build .
    
    echo "Running cpp_test..."
    ./cpp_test
    cd ..
else
    echo "CMake not found, skipping C++ tests."
fi

echo "All Tests Passed."
