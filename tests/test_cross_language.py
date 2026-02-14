import subprocess
import time
import os
import sys
import threading
import pytest
import shutil
import platform
import json

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
        
    # Helper to wrap command with namespace if needed
    def wrap_ns(cmd, ns_name):
        if os.environ.get("FUSION_VNET_MODE") == "1":
            # Use namespace execution for VNet
            # Note: WSL might need sudo, but passwordless sudo is assumed for tests
            # Or checks if we are already root.
            return ["sudo", "ip", "netns", "exec", ns_name] + cmd
        return cmd

    try:
        # C++ -> ns_ecu2 (Virtual Interface on Host)
        cpp_cmd = wrap_ns([os.path.abspath(cpp_exe_path)], "ns_ecu2")
        print(f"DEBUG: Executing C++: {cpp_cmd} cwd={CPP_DEMO_DIR}")
        cpp_proc = subprocess.Popen(
            cpp_cmd, 
            stdout=cpp_log, 
            stderr=subprocess.STDOUT,
            cwd=CPP_DEMO_DIR
        )
        cpp_log.close() # Release handle in parent
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
        # Rust -> ns_ecu1
        rust_cmd = wrap_ns([rust_bin], "ns_ecu1")
        print(f"DEBUG: Executing Rust: {rust_cmd} cwd={rust_demo_dir}")
        rust_proc = subprocess.Popen(
            rust_cmd,
            stdout=rust_log,
            stderr=subprocess.STDOUT,
            cwd=rust_demo_dir,
            env=rust_env
        )
        rust_log.close() # Release handle in parent
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
        # Python -> ns_ecu3
        py_cmd = wrap_ns([sys.executable, "-u", "main.py"], "ns_ecu3")
        print(f"DEBUG: Executing Python: {py_cmd} cwd={python_demo_dir}")
        python_proc = subprocess.Popen(
            py_cmd,
            stdout=python_log,
            stderr=subprocess.STDOUT,
            cwd=python_demo_dir,
            env=env
        )
        python_log.close() # Release handle in parent
    except Exception as e:
        print(f"ERROR: Python Popen failed: {e}")
        raise e
    time.sleep(5) # Allow interaction time

    yield

    # Cleanup (sudo pkill inside ns might be needed, or just kill the sudo wrapper)
    # Terminating the wrapper (sudo) usually propagates, but let's be safe
    # If we are in VNet mode, we might want to kill processes in namespaces explicitly in a real setup
    # but for now rely on Popen.terminate()
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
    print(f"DEBUG: Waiting for pattern '{pattern}' in {logfile}")
    while time.time() - start < timeout:
        if os.path.exists(logfile):
            try:
                # Open with shared read permission and handle encoding
                with open(logfile, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if pattern in content:
                        print(f"DEBUG: Found pattern '{pattern}'")
                        return True
            except PermissionError:
                # Can happen on Windows if file is locked
                print(f"DEBUG: PermissionError reading {logfile}")
                pass
            except Exception as e:
                print(f"Error reading log {logfile}: {e}")
        else:
            print(f"DEBUG: Log file {logfile} not found")
                
        time.sleep(0.5)
    return False

# Add project root to path to import tools
sys.path.append(PROJECT_ROOT)
from tools.fusion.utils import get_ipv6, patch_configs, get_local_ip

def setup_module(module):
    """Patch configuration to use detected interface (eth0/lo)"""
    ip = get_local_ip()
    
    # Force loopback on Windows for reliable local testing
    force_loopback = False
    if os.name == 'nt':
        print("DEBUG: Windows detected, forcing Loopback (127.0.0.1) for reliability")
        force_loopback = True
    
    if force_loopback:
        ip = "127.0.0.1"
    
    print(f"DEBUG: Patching configs using IP: {ip}")
    
    # Check for VNet setup (Host-Veth-Bridge topology)
    import subprocess
    vnet_map = {}
    
    # Check if veth_ns_ecu1 exists on Host
    has_vnet_iface = False
    vnet_iface_name = "veth_ns_ecu1" # Default fallback
    if platform.system() == "Linux":
        try:
            # Simple check for interface existence
            # Check widely for veth_ns_ecu1 OR veth_ns_ecu1_h0 (host side)
            res = subprocess.run("ip link show", shell=True, capture_output=True, text=True)
            if "veth_ns_ecu1_h0" in res.stdout:
                has_vnet_iface = True
                vnet_iface_name = "veth_ns_ecu1_h0"
            elif "veth_ns_ecu1" in res.stdout:
                has_vnet_iface = True
                vnet_iface_name = "veth_ns_ecu1"
        except: pass

    target_ifname = "eth0" # Standard default
    if has_vnet_iface or os.environ.get("FUSION_VNET_MODE") == "1":
        # VNet uses 10.0.1.x on Host interfaces
        vnet_map = {
            "rust_udp": "10.0.1.1",
            "rust_tcp": "10.0.1.1",
            "cpp_udp": "10.0.1.2",
            "python_v4_udp": "10.0.1.3",
            "python_v4_tcp": "10.0.1.3",
            "sd_multicast_v4": "224.224.224.245", 
            "sd_unicast_v4": "10.0.1.255" 
        }
        
        # We will use a flag to indicate VNet mode config patching, but NO namespace execution
        os.environ["FUSION_VNET_MODE"] = "1"
        print(f"DEBUG: VNet mode detected. Detecting interface name in ns_ecu1.")
        
        # Detect the data interface in ns_ecu1 (should be same everywhere)
        target_ifname = "veth0" # Valid default fallback if VNet is active
        try:
            # Use sudo to ensure we can see namespaces
            res = subprocess.run(["sudo", "ip", "netns", "exec", "ns_ecu1", "ip", "-o", "link", "show"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                parts = line.strip().split(": ")
                if len(parts) >= 2:
                    ifname = parts[1].split("@")[0].strip()
                    if ifname != "lo":
                        target_ifname = ifname
                        print(f"DEBUG: Detected interface '{target_ifname}' in namespace.")
                        break
        except Exception as e:
            print(f"WARNING: Interface detection failed: {e}")

    if os.environ.get("FUSION_VNET_MODE") == "1":
         # Manual patch for VNet
         config_path = os.path.join(PROJECT_ROOT, "examples/integrated_apps/config.json")
         with open(config_path, 'r') as f: data = json.load(f)
         
         if "interfaces" in data and "primary" in data["interfaces"]:
             # Update Interface Name to detected name (e.g., veth0)
             data["interfaces"]["primary"]["name"] = target_ifname
             
             eps = data["interfaces"]["primary"]["endpoints"]
             for name, new_ip in vnet_map.items():
                 if name in eps:
                    eps[name]["ip"] = new_ip
                    eps[name]["version"] = 4
             
             if "sd_multicast_v4" in eps:
                 eps["sd_multicast_v4"]["ip"] = vnet_map.get("sd_multicast_v4", "224.224.224.245")

         with open(config_path, 'w') as f: json.dump(data, f, indent=4)
         print("DEBUG: Patched config.json for VNet.")
    else:
        patch_configs(ip_v4=ip, root_dir=PROJECT_ROOT)

    # Backup Config for Debugging
    log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "cross_language"))
    os.makedirs(log_dir, exist_ok=True)
    shutil.copy(
        os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "config.json"),
        os.path.join(log_dir, "config.json")
    )
    print(f"DEBUG: Saved test config to {os.path.join(log_dir, 'config.json')}")

def has_multicast_support():
    """Check if we should run multicast tests (Skip only on Windows)"""
    return os.name != 'nt'

@pytest.mark.needs_multicast
@pytest.mark.skipif(not has_multicast_support(), reason="Multicast disabled on Windows for stability")
def test_rust_rpc_to_python(processes):
    """Verify Rust client calls Python StringService"""
    # Rust sends "Hello Python" to StringService.Reverse
    # Python logs "Reversing: Hello Python"
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Reversing"), "Rust->Python RPC failed: StringService did not receive request"

@pytest.mark.needs_multicast
def test_python_rpc_to_rust(processes):
    """Verify Python client calls Rust MathService"""
    # Python sends Add(10, 20) -> Rust
    # Rust logs "[MathService] Math.Add(10, 20)"
    # Python logs "Sending Add..."
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Sending Add"), "Python->Rust RPC failed: Client didn't send - Log pattern 'Sending Add' not found"
    
    # Check Rust log for the request
    # Pattern update: Log format is "[MathService] Math.Add"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "[MathService] Math.Add"), "Python->Rust RPC failed: Rust service didn't log request"

@pytest.mark.needs_multicast
def test_rust_to_cpp_math_inst2(processes):
    """Verify Rust client calls C++ MathService (Instance 2)"""
    # Rust sends Add(100, 200) to math-client-v1-inst2
    # C++ logs "[2] Add(100, 200)"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "[2] Add(100, 200)"), "Rust->C++ Math Inst 2 RPC failed"

@pytest.mark.needs_multicast
@pytest.mark.skipif(not has_multicast_support(), reason="Multicast disabled on Windows for stability")
def test_rust_to_python_math_inst3(processes):
    """Verify Rust client calls Python MathService (Instance 3)"""
    # Configured on 'python_tcp' (IPv6)
    # Rust sends Add(10, 20) to math-client-v2
    # Python logs "[3] Add(10, 20)"
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "[3] Add(10, 20)"), "Rust->Python Math Inst 3 RPC failed"

@pytest.mark.needs_multicast
def test_cpp_rpc_to_math(processes):
    """Verify C++ client calls MathService (Rust Instance 1)"""
    # C++ logs: "Math.Add Result:"
    # This should go to Rust Inst 1 based on config
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Math.Add Result:"), "C++->Math RPC failed"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Math.Add"), "C++->Rust Math Inst 1 failed"

@pytest.mark.needs_multicast
def test_cpp_event_updates(processes):
    """Verify C++ SortService updates trigger events"""
    # C++ logs: "Field 'status' changed"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Field 'status' changed"), "C++ did not trigger event/field update"

@pytest.mark.needs_multicast
def test_rust_consumes_event(processes):
    """Verify Rust client receives notification"""
    # Rust logs: "Received Notification"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Received Notification"), "Rust did not receive event notification"

@pytest.mark.needs_multicast
@pytest.mark.skipif(not has_multicast_support(), reason="Multicast disabled on Windows for stability")
def test_python_to_cpp_sort(processes):
    """Verify Python client calls C++ SortService"""
    # Python sends [5, 3, 1, 4, 2] to SortService
    # C++ logs: "Sorting 5 items"
    # Python logs: "Sending Sort..."
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Sending Sort..."), "Python->C++ Sort: Client didn't send"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Sorting 5 items"), "Python->C++ Sort: Server didn't receive/log"

