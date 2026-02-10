import subprocess
import time
import os
import sys
import threading
import pytest
import shutil
import platform

# Path setup
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(f"DEBUG: PROJECT_ROOT calculated as: {PROJECT_ROOT}")
# C++ Demo is now in its own sub-build
CPP_DEMO_DIR = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "cpp_app")
print(f"DEBUG: CPP_DEMO_DIR: {CPP_DEMO_DIR}")
# Check build artifact location first (Nested, Root, and deep sub-build)
ARTIFACT_BUILD_PATH_NESTED = os.path.join(PROJECT_ROOT, "build", "examples", "integrated_apps", "cpp_app", "cpp_app")
ARTIFACT_BUILD_PATH_ROOT = os.path.join(PROJECT_ROOT, "build", "cpp_app")
LOCAL_BUILD_PATH = os.path.join(CPP_DEMO_DIR, "build", "Release", "cpp_app.exe")
# Deeply nested path found in MSVC build
DEEP_BUILD_PATH = os.path.join(CPP_DEMO_DIR, "build", "fusion_hawking_core", "examples", "integrated_apps", "cpp_app", "Release", "cpp_app.exe")
# WSL Build Path
WSL_BUILD_PATH = os.path.join(PROJECT_ROOT, "build_wsl", "examples", "integrated_apps", "cpp_app", "cpp_app")

if os.name == 'nt':
    ARTIFACT_BUILD_PATH_NESTED += ".exe"
    # Root might also have a Release folder if built via main script
    if not os.path.exists(ARTIFACT_BUILD_PATH_ROOT + ".exe"):
        ARTIFACT_BUILD_PATH_ROOT = os.path.join(PROJECT_ROOT, "build", "Release", "cpp_app.exe")
    else:
        ARTIFACT_BUILD_PATH_ROOT += ".exe"

def find_cpp_exe():
    """Find the C++ executable, accounting for various build layouts"""
    is_windows = os.name == 'nt'
    
    # Check default locations
    candidates = [
        ARTIFACT_BUILD_PATH_ROOT,
        ARTIFACT_BUILD_PATH_NESTED,
        DEEP_BUILD_PATH,
        LOCAL_BUILD_PATH,
    ]
    
    # Only add WSL path if not on Windows, or if we really have to (but it's likely ELF)
    if platform.system() == "Windows":
        candidates = [c for c in candidates if "build_wsl" not in c]
        candidates = [c if c.endswith(".exe") else c + ".exe" for c in candidates]
    else: # Add WSL path only if not on Windows
        candidates.append(WSL_BUILD_PATH)
    
    for cand in candidates:
        if is_windows and not cand.lower().endswith(".exe"):
            continue
            
        print(f"DEBUG: Checking {cand} -> {os.path.exists(cand)}")
        if os.path.exists(cand):
            # On Windows, double check it's not a directory (unlikely but safe)
            if not os.path.isdir(cand):
                print(f"DEBUG: Found C++ EXE at {cand}")
                return cand
            
    # Fallback: Walk the build config to find it
    search_root = os.path.join(CPP_DEMO_DIR, "build")
    target_name = "cpp_app.exe" if is_windows else "cpp_app"
    
    if os.path.exists(search_root):
        for root, dirs, files in os.walk(search_root):
            if target_name in files:
                found_path = os.path.join(root, target_name)
                # Skip build_wsl if we are on Windows
                if is_windows and "build_wsl" in found_path:
                    continue
                return found_path
            
    return LOCAL_BUILD_PATH # Default fallback

CPP_EXE = find_cpp_exe()

def get_log_path(name):
    # Always look up environment variable to avoid stale global state
    log_dir = os.environ.get("FUSION_LOG_DIR", os.getcwd())
    return os.path.join(log_dir, name)

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
    rust_bin = os.path.join(rust_demo_dir, "target", "debug", "rust_app_demo")
    if sys.platform == "win32": rust_bin += ".exe"
    
    if not os.path.exists(rust_bin):
        print("DEBUG: Building Rust app...")
        subprocess.check_call(["cargo", "build"], cwd=rust_demo_dir)
    else:
        print(f"DEBUG: Rust app exists at {rust_bin}, skipping build.")

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
        
    try:
        print(f"DEBUG: Executing C++: {[os.path.abspath(cpp_exe_path)]} cwd={CPP_DEMO_DIR}")
        cpp_proc = subprocess.Popen(
            [os.path.abspath(cpp_exe_path)], 
            stdout=cpp_log, 
            stderr=subprocess.STDOUT,
            cwd=CPP_DEMO_DIR
        )
    except FileNotFoundError as e:
        print(f"ERROR: C++ Popen failed: {e}")
        raise e

    time.sleep(2) # Let it start

    # 2. Start Rust App (Provider)
    rust_log_path = get_log_path("rust_integration.log")
    rust_log = open(rust_log_path, "w")
    rust_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "rust_app")
    # Execute binary directly to avoid cargo overhead/rebuilds
    # Binary name depends on Cargo.toml package name: "rust_app_demo"
    rust_bin = os.path.join(rust_demo_dir, "target", "debug", "rust_app_demo")
    if sys.platform == "win32": rust_bin += ".exe"
    
    rust_env = os.environ.copy()
    rust_env["RUST_LOG"] = "debug"

    try:
        print(f"DEBUG: Executing Rust: {[rust_bin]} cwd={rust_demo_dir}")
        rust_proc = subprocess.Popen(
            [rust_bin],
            stdout=rust_log,
            stderr=subprocess.STDOUT,
            cwd=rust_demo_dir,
            env=rust_env
        )
    except FileNotFoundError as e:
        print(f"ERROR: Rust Popen failed: {e}")
        raise e

    time.sleep(3) # Let it start and settle

    # 3. Start Python App (Client/Provider)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
    
    python_log_path = get_log_path("python_integration.log")
    python_log = open(python_log_path, "w")
    python_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "python_app")
    try:
        print(f"DEBUG: Executing Python: {[sys.executable, '-u', 'main.py']} cwd={python_demo_dir}")
        python_proc = subprocess.Popen(
            [sys.executable, "-u", "main.py"],
            stdout=python_log,
            stderr=subprocess.STDOUT,
            cwd=python_demo_dir,
            env=env
        )
    except Exception as e:
        print(f"ERROR: Python Popen failed: {e}")
        raise e
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
from tools.fusion.utils import get_ipv6, patch_configs, get_local_ip

def setup_module(module):
    """Patch configuration to use detected interface (eth0/lo)"""
    print(f"DEBUG: Patching configs using detected IP: {get_local_ip()}")
    patch_configs(ip_v4=get_local_ip(), root_dir=PROJECT_ROOT)

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

@pytest.mark.skipif(not has_ipv6(), reason="System lacks global IPv6 capability")
def test_python_to_cpp_sort(processes):
    """Verify Python client calls C++ SortService"""
    # Python sends [5, 3, 1, 4, 2] to SortService
    # C++ logs: "Sorting 5 items"
    # Python logs: "Sending Sort..."
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Sending Sort..."), "Python->C++ Sort: Client didn't send"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Sorting 5 items"), "Python->C++ Sort: Server didn't receive/log"

