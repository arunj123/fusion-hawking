import subprocess
import time
import os
import sys
import threading
import pytest
import shutil

# Path setup
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
CPP_EXE = os.path.join(BUILD_DIR, "Debug", "cpp_app.exe") if os.name == 'nt' else os.path.join(BUILD_DIR, "cpp_app")

@pytest.fixture(scope="module")
def build_cpp():
    """Ensure C++ app is built"""
    if not os.path.exists(CPP_EXE):
        if not os.path.exists(BUILD_DIR):
            os.makedirs(BUILD_DIR)
        
        # Configure
        subprocess.check_call(["cmake", "-S", ".", "-B", "build"], cwd=PROJECT_ROOT)
        # Build
        subprocess.check_call(["cmake", "--build", "build", "--config", "Debug", "--target", "cpp_app"], cwd=PROJECT_ROOT)

@pytest.fixture(scope="module")
def processes(build_cpp):
    """Start all three demo apps and yield them, then cleanup"""
    
    # 1. Start C++ App
    cpp_log = open("cpp_integration.log", "w")
    cpp_proc = subprocess.Popen(
        [CPP_EXE], 
        stdout=cpp_log, 
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT
    )
    time.sleep(1) # Let it start

    # 2. Start Rust App
    rust_log = open("rust_integration.log", "w")
    rust_proc = subprocess.Popen(
        ["cargo", "run", "--example", "rust_app"],
        stdout=rust_log,
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT
    )
    time.sleep(2) # Let it start

    # 3. Start Python App
    env = os.environ.copy()
    env["PYTHONPATH"] = f"src/python;build;build/generated/python"
    
    python_log = open("python_integration.log", "w")
    python_proc = subprocess.Popen(
        [sys.executable, "-u", "examples/integrated_apps/python_app/main.py"],
        stdout=python_log,
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT,
        env=env
    )
    time.sleep(5) # Allow interaction time

    yield

    # Cleanup
    cpp_proc.terminate()
    rust_proc.terminate()
    python_proc.terminate()
    
    cpp_proc.wait()
    rust_proc.wait()
    python_proc.wait()
    
    cpp_log.close()
    rust_log.close()
    python_log.close()

def wait_for_log_pattern(logfile, pattern, timeout=15):
    """Wait for a pattern to appear in a log file"""
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(logfile):
            try:
                # Open with shared read permission and handle encoding
                with open(logfile, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if pattern in content:
                        return True
            except PermissionError:
                # Can happen on Windows if file is locked
                pass
            except Exception as e:
                print(f"Error reading log {logfile}: {e}")
                
        time.sleep(0.5)
    return False

def test_rust_rpc_to_python(processes):
    """Verify Rust client calls Python StringService"""
    # Rust sends "Hello Python" to StringService.Reverse
    # Python logs "Reversing: Hello Python"
    assert wait_for_log_pattern("python_integration.log", "Reversing"), "Rust->Python RPC failed: StringService did not receive request"

def test_python_rpc_to_rust(processes):
    """Verify Python client calls Rust MathService"""
    # Python sends Add(10, 20) -> Rust
    # Rust logs "[MathService] Math.Add(10, 20)"
    # Python logs "Sending Add..."
    assert wait_for_log_pattern("python_integration.log", "Sending Add"), "Python->Rust RPC failed: Client didn't send - Log pattern 'Sending Add' not found"
    
    # Check Rust log for the request
    # Pattern update: Log format is "[MathService] Math.Add"
    assert wait_for_log_pattern("rust_integration.log", "[MathService] Math.Add"), "Python->Rust RPC failed: Rust service didn't log request"

def test_cpp_rpc_to_math(processes):
    """Verify C++ client calls MathService (Rust or Python)"""
    # C++ logs: "Math.Add Result: 30"
    assert wait_for_log_pattern("cpp_integration.log", "Math.Add Result:"), "C++->Math RPC failed"

def test_cpp_event_updates(processes):
    """Verify C++ SortService updates trigger events"""
    # C++ logs: "Field 'status' changed"
    assert wait_for_log_pattern("cpp_integration.log", "Field 'status' changed"), "C++ did not trigger event/field update"

def test_rust_consumes_event(processes):
    """Verify Rust client receives notification"""
    # Rust logs: "Received Notification"
    assert wait_for_log_pattern("rust_integration.log", "Received Notification"), "Rust did not receive event notification"
