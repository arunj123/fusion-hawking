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

# Add project root to path to import tools
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from tools.fusion.utils import _get_env as get_environment

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

def generate_config(env, output_dir):
    """Generate configuration for Integrated Apps demo (Test Cross Language)"""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "config.json")
    
    # Logic adapted from legacy patching and refactored test.py
    
    ipv4 = env.primary_ip or "127.0.0.1"
    # Force loopback on Windows for reliable local testing if not in VNet
    is_vnet = os.environ.get("FUSION_VNET_MODE") == "1"
    if os.name == 'nt' and not is_vnet:
        ipv4 = "127.0.0.1"

    primary_iface = env.primary_interface or ("Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo")
    
    # VNet Handling
    if is_vnet:
        # Check if we can detect the interface name in namespaces
        # This logic comes from old setup_module
        try:
             # Use sudo to ensure we can see namespaces
             res = subprocess.run(["sudo", "ip", "netns", "exec", "ns_ecu1", "ip", "-o", "link", "show"], capture_output=True, text=True)
             for line in res.stdout.splitlines():
                 parts = line.strip().split(": ")
                 if len(parts) >= 2:
                     ifname = parts[1].split("@")[0].strip()
                     if ifname != "lo":
                         primary_iface = ifname
                         print(f"DEBUG: Detected VNet interface '{primary_iface}' in namespace.")
                         break
        except Exception: pass

    # Define Endpoints and Services
    # Mirroring examples/integrated_apps/config.json structure
    
    endpoints = {
        "rust_udp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "udp"},
        "rust_tcp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "tcp"},
        "python_tcp": {"ip": "::1" if env.has_ipv6 else ipv4, "version": 6 if env.has_ipv6 else 4, "port": 0, "protocol": "tcp"}, 
        "python_v4_tcp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "tcp"},
        "python_v4_udp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "udp"},
        "cpp_udp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "udp"},
        "js_udp": {"ip": "127.0.0.1", "version": 4, "port": 0, "protocol": "udp"},
        "sd_multicast_v4": {"ip": "224.224.224.245", "port": 30890, "version": 4, "protocol": "udp"},
        "sd_unicast_v4": {"ip": ipv4, "port": 0, "version": 4, "protocol": "udp"},
    }
    
    # VNet Overrides
    if is_vnet:
        endpoints.update({
            "rust_udp": {"ip": "10.0.1.1", "version": 4, "port": 0, "protocol": "udp"},
            "rust_tcp": {"ip": "10.0.1.1", "version": 4, "port": 0, "protocol": "tcp"},
            "cpp_udp": {"ip": "10.0.1.2", "version": 4, "port": 0, "protocol": "udp"},
            "python_v4_udp": {"ip": "10.0.1.3", "version": 4, "port": 0, "protocol": "udp"},
            "python_v4_tcp": {"ip": "10.0.1.3", "version": 4, "port": 0, "protocol": "tcp"},
            "sd_unicast_v4": {"ip": "10.0.1.255", "version": 4, "port": 0, "protocol": "udp"} # Broadcast for SD?
        })
    
    config = {
        "interfaces": {
            "primary": {
                "name": primary_iface,
                "endpoints": endpoints,
                "sd": {
                    "endpoint_v4": "sd_multicast_v4"
                }
            }
        },
        "instances": {
             "rust_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "providing": {
                    "math-service": {"service_id": 4097, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}},
                    "eco-service": {"service_id": 4098, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_tcp"}},
                    "complex-service": {"service_id": 16385, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}}
                },
                "required": {
                    "math-client-v2": {"service_id": 4097, "instance_id": 3, "major_version": 2, "find_on": ["primary"]},
                    "math-client-v1-inst2": {"service_id": 4097, "instance_id": 2, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "diag-client": {"service_id": 20481, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                },
                "sd": {"cycle_offer_ms": 1000}
            },
            "python_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "providing": {
                    "string-service": {"service_id": 8193, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_udp"}},
                    "diagnostic-service": {"service_id": 20481, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_tcp"}},
                    "math-service": {"service_id": 4097, "instance_id": 3, "major_version": 2, "offer_on": {"primary": "python_v4_tcp"}}
                },
                "required": {
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "eco-client": {"service_id": 4098, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "complex-client": {"service_id": 16385, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sensor-client": {"service_id": 24577, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            },
            "cpp_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "providing": {
                    "sort-service": {"service_id": 12289, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "sensor-service": {"service_id": 24577, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "math-service": {"service_id": 4097, "instance_id": 2, "major_version": 1, "offer_on": {"primary": "cpp_udp"}}
                },
                "required": {
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            },
            "js_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "required": {
                     "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                     "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            }
        }
    }
    
    if env.has_ipv6:
         config["interfaces"]["primary"]["endpoints"]["sd_multicast_v6"] = {"ip": "ff0e::4:C", "port": 31890, "version": 6, "protocol": "udp"}
         config["interfaces"]["primary"]["endpoints"]["sd_unicast_v6"] = {"ip": "::1", "port": 31890, "version": 6, "protocol": "udp"}
         config["interfaces"]["primary"]["sd"]["endpoint_v6"] = "sd_multicast_v6"

    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        
    print(f"DEBUG: Generated config at {config_path}")
    return config_path

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
def generated_config():
    """Generate the config file for this test module"""
    env = get_environment()
    log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "cross_language"))
    os.makedirs(log_dir, exist_ok=True)
    return generate_config(env, log_dir)

@pytest.fixture(scope="module")
def processes(build_cpp, build_rust, generated_config):
    """Start all three demo apps and yield them, then cleanup"""
    
    config_path = os.path.abspath(generated_config)
    
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
        # C++ -> ns_ecu2
        # Setup command with config path arg
        cmd_args = [os.path.abspath(cpp_exe_path), config_path]
        cpp_cmd = wrap_ns(cmd_args, "ns_ecu2")
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
    rust_bin = os.path.join(rust_demo_dir, "target", "debug", "rust_app_demo")
    if sys.platform == "win32": rust_bin += ".exe"
    
    rust_env = os.environ.copy()
    rust_env["RUST_LOG"] = "debug"

    try:
        # Rust -> ns_ecu1
        cmd_args = [rust_bin, config_path]
        rust_cmd = wrap_ns(cmd_args, "ns_ecu1")
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
        cmd_args = [sys.executable, "-u", "main.py", config_path]
        py_cmd = wrap_ns(cmd_args, "ns_ecu3")
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
                pass
            except Exception as e:
                print(f"Error reading log {logfile}: {e}")
        else:
            print(f"DEBUG: Log file {logfile} not found")
                
        time.sleep(0.5)
    return False

def has_multicast_support():
    """Check if we should run multicast tests (Skip only on Windows)"""
    return os.name != 'nt'

@pytest.mark.needs_multicast
@pytest.mark.skipif(not has_multicast_support(), reason="Multicast disabled on Windows for stability")
def test_rust_rpc_to_python(processes):
    """Verify Rust client calls Python StringService"""
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Reversing"), "Rust->Python RPC failed"

@pytest.mark.needs_multicast
def test_python_rpc_to_rust(processes):
    """Verify Python client calls Rust MathService"""
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Sending Add"), "Python->Rust RPC failed: Client didn't send"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "[MathService] Math.Add"), "Python->Rust RPC failed: Server no receive"

@pytest.mark.needs_multicast
def test_rust_to_cpp_math_inst2(processes):
    """Verify Rust client calls C++ MathService (Instance 2)"""
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "[2] Add(100, 200)"), "Rust->C++ Math Inst 2 RPC failed"

@pytest.mark.needs_multicast
@pytest.mark.skipif(not has_multicast_support(), reason="Multicast disabled on Windows for stability")
def test_rust_to_python_math_inst3(processes):
    """Verify Rust client calls Python MathService (Instance 3)"""
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "[3] Add(10, 20)"), "Rust->Python Math Inst 3 RPC failed"

@pytest.mark.needs_multicast
def test_cpp_rpc_to_math(processes):
    """Verify C++ client calls MathService (Rust Instance 1)"""
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Math.Add Result:"), "C++->Math RPC failed"
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Math.Add"), "C++->Rust Math Inst 1 failed"

@pytest.mark.needs_multicast
def test_cpp_event_updates(processes):
    """Verify C++ SortService updates trigger events"""
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Field 'status' changed"), "C++ did not trigger event"

@pytest.mark.needs_multicast
def test_rust_consumes_event(processes):
    """Verify Rust client receives notification"""
    assert wait_for_log_pattern(get_log_path("rust_integration.log"), "Received Notification"), "Rust did not receive event"

@pytest.mark.needs_multicast
@pytest.mark.skipif(not has_multicast_support(), reason="Multicast disabled on Windows for stability")
def test_python_to_cpp_sort(processes):
    """Verify Python client calls C++ SortService"""
    assert wait_for_log_pattern(get_log_path("python_integration.log"), "Sending Sort..."), "Python->C++ Sort: Client didn't send"
    assert wait_for_log_pattern(get_log_path("cpp_integration.log"), "Sorting 5 items"), "Python->C++ Sort: Server didn't receive"
