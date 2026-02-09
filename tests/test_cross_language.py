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
CPP_DEMO_DIR = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "cpp_app")
# Check build artifact location first (Nested, Root, and deep sub-build)
ARTIFACT_BUILD_PATH_NESTED = os.path.join(PROJECT_ROOT, "build", "examples", "integrated_apps", "cpp_app", "cpp_app")
ARTIFACT_BUILD_PATH_ROOT = os.path.join(PROJECT_ROOT, "build", "cpp_app")
LOCAL_BUILD_PATH = os.path.join(CPP_DEMO_DIR, "build", "Release", "cpp_app.exe")
# Deeply nested path found in MSVC build
DEEP_BUILD_PATH = os.path.join(CPP_DEMO_DIR, "build", "fusion_hawking_core", "examples", "integrated_apps", "cpp_app", "Release", "cpp_app.exe")

if os.name == 'nt':
    ARTIFACT_BUILD_PATH_NESTED += ".exe"
    # Root might also have a Release folder if built via main script
    if not os.path.exists(ARTIFACT_BUILD_PATH_ROOT + ".exe"):
        ARTIFACT_BUILD_PATH_ROOT = os.path.join(PROJECT_ROOT, "build", "Release", "cpp_app.exe")
    else:
        ARTIFACT_BUILD_PATH_ROOT += ".exe"

def find_cpp_exe():
    """Find the C++ executable, accounting for various build layouts"""
    # Check default locations
    candidates = [
        ARTIFACT_BUILD_PATH_ROOT,
        ARTIFACT_BUILD_PATH_NESTED,
        DEEP_BUILD_PATH,
        LOCAL_BUILD_PATH
    ]
    
    for path in candidates:
        if os.path.exists(path):
            return path
            
    # Fallback: Walk the build config to find it
    for root, dirs, files in os.walk(os.path.join(CPP_DEMO_DIR, "build")):
        if "cpp_app.exe" in files:
            return os.path.join(root, "cpp_app.exe")
            
    return LOCAL_BUILD_PATH # Default fallback

CPP_EXE = find_cpp_exe()

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
def build_rust():
    """Ensure Rust app is built"""
    rust_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "rust_app")
    # Build release to match C++? Or debug is fine.
    subprocess.check_call(["cargo", "build"], cwd=rust_demo_dir)

@pytest.fixture(scope="module")
def processes(build_cpp, build_rust):
    """Start all three demo apps and yield them, then cleanup"""
    
    # 1. Start C++ App (Client of Rust, Provider for others)
    cpp_log_path = get_log_path("cpp_integration.log")
    cpp_log = open(cpp_log_path, "w")
    # Resolve CPP_EXE dynamically after build
    cpp_exe_path = find_cpp_exe()
    if not os.path.exists(cpp_exe_path):
        print(f"WARNING: C++ EXE not found at {cpp_exe_path}. Searching...")
        # Try one more search in case of race?
        time.sleep(1)
        cpp_exe_path = find_cpp_exe()
        
    cpp_proc = subprocess.Popen(
        [os.path.abspath(cpp_exe_path)], 
        stdout=cpp_log, 
        stderr=subprocess.STDOUT,
        cwd=CPP_DEMO_DIR
    )
    time.sleep(2) # Let it start

    # 2. Start Rust App (Provider)
    rust_log_path = get_log_path("rust_integration.log")
    rust_log = open(rust_log_path, "w")
    rust_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "rust_app")
    # Execute binary directly to avoid cargo overhead/rebuilds
    # Binary name depends on Cargo.toml package name: "rust_app_demo"
    rust_bin = os.path.join(rust_demo_dir, "target", "debug", "rust_app_demo")
    if sys.platform == "win32": rust_bin += ".exe"
    
    rust_proc = subprocess.Popen(
        [rust_bin],
        stdout=rust_log,
        stderr=subprocess.STDOUT,
        cwd=rust_demo_dir
    )
    time.sleep(3) # Let it start and settle

    # 3. Start Python App (Client/Provider)
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

def wait_for_log_pattern(logfile, pattern, timeout=60):
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

# Add project root to path to import tools
sys.path.append(PROJECT_ROOT)
from tools.fusion.utils import get_ipv6, patch_configs

def setup_module(module):
    """Patch configuration to use loopback for safe local testing"""
    print("DEBUG: Patching configs to force loopback for tests...")
    patch_configs(ip_v4="127.0.0.1", root_dir=PROJECT_ROOT, ip_v6="::1")

def has_ipv6():
    """Check if we have a usable IPv6 address (global or local unique)"""
    return get_ipv6() is not None

@pytest.mark.skipif(not has_ipv6(), reason="System lacks global IPv6 capability")
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

def test_rust_to_cpp_math_inst2(processes):
    """Verify Rust client calls C++ MathService (Instance 2)"""
    # Rust sends Add(100, 200) to math-client-v1-inst2
    # C++ logs "[2] Add(100, 200)"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "[2] Add(100, 200)"), "Rust->C++ Math Inst 2 RPC failed"

@pytest.mark.skipif(not has_ipv6(), reason="System lacks global IPv6 capability")
def test_rust_to_python_math_inst3(processes):
    """Verify Rust client calls Python MathService (Instance 3)"""
    # Configured on 'python_tcp' (IPv6)
    # Rust sends Add(10, 20) to math-client-v2
    # Python logs "[3] Add(10, 20)"
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "[3] Add(10, 20)"), "Rust->Python Math Inst 3 RPC failed"

def test_cpp_rpc_to_math(processes):
    """Verify C++ client calls MathService (Rust Instance 1)"""
    # C++ logs: "Math.Add Result:"
    # This should go to Rust Inst 1 based on config
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Math.Add Result:"), "C++->Math RPC failed"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Math.Add"), "C++->Rust Math Inst 1 failed"

def test_cpp_event_updates(processes):
    """Verify C++ SortService updates trigger events"""
    # C++ logs: "Field 'status' changed"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Field 'status' changed"), "C++ did not trigger event/field update"

def test_rust_consumes_event(processes):
    """Verify Rust client receives notification"""
    # Rust logs: "Received Notification"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Received Notification"), "Rust did not receive event notification"
