import subprocess
import time
import os
import sys
import threading
import pytest
import shutil

# Path setup
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# C++ Demo is now in its own sub-build
# C++ Demo is now in its own sub-build
CPP_DEMO_DIR = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "cpp_app")
# Check build artifact location first
ARTIFACT_BUILD_PATH = os.path.join(PROJECT_ROOT, "build", "examples", "integrated_apps", "cpp_app", "cpp_app")
LOCAL_BUILD_PATH = os.path.join(CPP_DEMO_DIR, "build", "cpp_app")

if os.name == 'nt':
    ARTIFACT_BUILD_PATH += ".exe"
    LOCAL_BUILD_PATH = os.path.join(CPP_DEMO_DIR, "build", "Release", "cpp_app.exe")

CPP_EXE = ARTIFACT_BUILD_PATH if os.path.exists(ARTIFACT_BUILD_PATH) else LOCAL_BUILD_PATH

# Log Directory setup
LOG_DIR = os.environ.get("FUSION_LOG_DIR", os.getcwd())

def get_log_path(name):
    return os.path.join(LOG_DIR, name)

@pytest.fixture(scope="module")
def build_cpp():
    """Ensure C++ app is built"""
    if not os.path.exists(CPP_EXE):
        build_dir = os.path.join(CPP_DEMO_DIR, "build")
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)
        
        # Configure
        subprocess.check_call(["cmake", ".."], cwd=build_dir)
        # Build
        subprocess.check_call(["cmake", "--build", ".", "--config", "Release"], cwd=build_dir)

@pytest.fixture(scope="module")
def processes(build_cpp):
    """Start all three demo apps and yield them, then cleanup"""
    
    # 1. Start C++ App
    cpp_log_path = get_log_path("cpp_integration.log")
    cpp_log = open(cpp_log_path, "w")
    cpp_proc = subprocess.Popen(
        [os.path.abspath(CPP_EXE)], 
        stdout=cpp_log, 
        stderr=subprocess.STDOUT,
        cwd=CPP_DEMO_DIR
    )
    time.sleep(1) # Let it start

    # 2. Start Rust App
    rust_log_path = get_log_path("rust_integration.log")
    rust_log = open(rust_log_path, "w")
    rust_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "rust_app")
    rust_proc = subprocess.Popen(
        ["cargo", "run"],
        stdout=rust_log,
        stderr=subprocess.STDOUT,
        cwd=rust_demo_dir
    )
    time.sleep(2) # Let it start

    # 3. Start Python App
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
    
    python_log_path = get_log_path("python_integration.log")
    python_log = open(python_log_path, "w")
    python_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "python_app")
    python_proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        stdout=python_log,
        stderr=subprocess.STDOUT,
        cwd=python_demo_dir,
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
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Reversing"), "Rust->Python RPC failed: StringService did not receive request"

def test_python_rpc_to_rust(processes):
    """Verify Python client calls Rust MathService"""
    # Python sends Add(10, 20) -> Rust
    # Rust logs "[MathService] Math.Add(10, 20)"
    # Python logs "Sending Add..."
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Sending Add"), "Python->Rust RPC failed: Client didn't send - Log pattern 'Sending Add' not found"
    
    # Check Rust log for the request
    # Pattern update: Log format is "[MathService] Math.Add"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "[MathService] Math.Add"), "Python->Rust RPC failed: Rust service didn't log request"

def test_cpp_rpc_to_math(processes):
    """Verify C++ client calls MathService (Rust or Python)"""
    # C++ logs: "Math.Add Result: 30"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Math.Add Result:"), "C++->Math RPC failed"

def test_cpp_event_updates(processes):
    """Verify C++ SortService updates trigger events"""
    # C++ logs: "Field 'status' changed"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Field 'status' changed"), "C++ did not trigger event/field update"

def test_rust_consumes_event(processes):
    """Verify Rust client receives notification"""
    # Rust logs: "Received Notification"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Received Notification"), "Rust did not receive event notification"
