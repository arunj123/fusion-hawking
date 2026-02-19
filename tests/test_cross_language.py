import subprocess
import time
import os
import sys
import threading
import pytest
import shutil
import platform
import json

from tools.fusion.environment import NetworkEnvironment
from tools.fusion.integration import IntegrationTestContext
from tools.fusion.config_gen import SmartConfigFactory
from tools.fusion.utils import to_wsl, find_binary

# Global environment
ENV = NetworkEnvironment()
if not ENV.interfaces:
    ENV.detect()
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

@pytest.fixture(scope="module")
def ctx():
    """Integration Test Context for cross-language tests.
    """
    factory = SmartConfigFactory(ENV)
    
    # Distributed VNet: Apps in different namespaces
    # Fallback: Single namespace or None (Host)
    ns_rust = "ns_ecu1" if ENV.has_vnet else None
    ns_cpp = "ns_ecu2" if ENV.has_vnet else None
    ns_python = "ns_ecu3" if ENV.has_vnet else None
    
    with IntegrationTestContext("test_cross_language") as c:
        # SmartConfigFactory handles interface/IP resolution — no manual patching needed
        config_ret = factory.generate_integrated_apps(c.log_dir)
        
        if os.path.isdir(config_ret):
            # Distributed VNet (3 configs)
            rust_config = to_wsl(os.path.join(config_ret, "config_ecu1.json"))
            cpp_config = to_wsl(os.path.join(config_ret, "config_ecu2.json"))
            py_config = to_wsl(os.path.join(config_ret, "config_ecu3.json"))
        else:
            # Single Config
            common = to_wsl(config_ret)
            rust_config = common
            cpp_config = common
            py_config = common

        # 1. C++ (ECU2)
        cpp_exe = find_binary("cpp_app", search_dirs=[
            os.path.join(PROJECT_ROOT, "build_linux", "examples", "integrated_apps", "cpp_app"),
            os.path.join(PROJECT_ROOT, "build_wsl", "examples", "integrated_apps", "cpp_app"),
            os.path.join(PROJECT_ROOT, "build", "Release", "examples", "integrated_apps", "cpp_app"), # Windows Release
            os.path.join(PROJECT_ROOT, "build", "examples", "integrated_apps", "cpp_app"), # Linux default
        ])
        if cpp_exe:
             c.add_runner("cpp", [cpp_exe, cpp_config], ns=ns_cpp).start()
        
        # 2. Rust (ECU1)
        rust_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "rust_app")
        rust_bin = find_binary("rust_app_demo", search_dirs=[
            os.path.join(rust_demo_dir, "target", "debug"),
            os.path.join(rust_demo_dir, "target", "release"),
            os.path.join(PROJECT_ROOT, "target", "debug"),
            os.path.join(PROJECT_ROOT, "target", "release"),
        ])
        if rust_bin:
            env = os.environ.copy()
            env["RUST_LOG"] = "debug"
            c.add_runner("rust", [rust_bin, rust_config], cwd=rust_demo_dir, env=env, ns=ns_rust).start()

        # 3. Python (ECU3)
        py_demo_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "python_app")
        env = os.environ.copy() 
        env["PYTHONPATH"] = os.pathsep.join([os.path.join(PROJECT_ROOT, "src", "python"), 
                                            os.path.join(PROJECT_ROOT, "build"),
                                            os.path.join(PROJECT_ROOT, "build", "generated", "integrated_apps", "python")])
        # Propagate base port if set
        if os.environ.get("FUSION_BASE_PORT"):
            env["FUSION_BASE_PORT"] = os.environ["FUSION_BASE_PORT"]
            
        c.add_runner("python", [sys.executable, "-u", "main.py", py_config], cwd=py_demo_dir, env=env, ns=ns_python).start()

        # 4. JS (ECU3 - collocated with Python)
        js_app_dir = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "js_app")
        if os.path.exists(js_app_dir):
            js_bin = os.path.join(js_app_dir, "dist", "index.js")
            if not os.path.exists(js_bin):
                 # Fallback for local development, but in CI we expect pre-built
                 npm_bin = "npm.cmd" if os.name == 'nt' else "npm"
                 print(f"[WARN] JS binary not found at {js_bin}. Attempting runtime build in {js_app_dir}...")
                 res_inst = subprocess.run([npm_bin, "install"], cwd=js_app_dir, capture_output=True, text=True)
                 if res_inst.returncode != 0:
                     print(f"[ERROR] npm install failed:\n{res_inst.stdout}\n{res_inst.stderr}")
                 
                 res_build = subprocess.run([npm_bin, "run", "build"], cwd=js_app_dir, capture_output=True, text=True)
                 if res_build.returncode != 0:
                     print(f"[ERROR] npm run build failed:\n{res_build.stdout}\n{res_build.stderr}")
            
            if os.path.exists(js_bin):
                print(f"[INFO] Starting JS runner: node dist/index.js {py_config}")
                c.add_runner("js", ["node", "dist/index.js", py_config], cwd=js_app_dir, ns=ns_python).start()
            else:
                # In CI, if target is not 'js' or 'all', it's okay to skip
                print(f"[ERROR] JS App Demo binary missing at {js_bin} even after build attempt.")
                # Ensure we don't have a None runner when we expect one? 
                # Actually, the test checks for None.

        time.sleep(5)
        yield c

def wait_for_log_pattern(logfile, pattern, timeout=60):
    """Wait for a pattern to appear in a log file"""
    start = time.time()
    print(f"DEBUG: Waiting for pattern '{pattern}' in {logfile}")
    while time.time() - start < timeout:
        if os.path.exists(logfile):
            try:
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
def test_rust_rpc_to_python(ctx):
    """Verify Rust client calls Python StringService"""
    if ctx.get_runner("python") is None: pytest.skip("Python runner not available")
    if ctx.get_runner("rust") is None: pytest.skip("Rust runner not available")
    ctx.get_runner("python").clear_output()
    assert ctx.get_runner("python").wait_for_output("Reversing", timeout=20), "Rust->Python RPC failed"

@pytest.mark.needs_multicast
def test_python_rpc_to_rust(ctx):
    """Verify Python client calls Rust MathService"""
    if ctx.get_runner("python") is None: pytest.skip("Python runner not available")
    if ctx.get_runner("rust") is None: pytest.skip("Rust runner not available")
    ctx.get_runner("python").clear_output()
    ctx.get_runner("rust").clear_output()
    assert ctx.get_runner("python").wait_for_output("Sending Add", timeout=10)
    assert ctx.get_runner("rust").wait_for_output(r"\[MathService\] Math\.Add", timeout=20)

@pytest.mark.needs_multicast
def test_rust_to_cpp_math_inst2(ctx):
    """Verify Rust client calls C++ MathService (Instance 2)"""
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    if ctx.get_runner("rust") is None: pytest.skip("Rust runner not available")
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    ctx.get_runner("cpp").clear_output()
    assert ctx.get_runner("cpp").wait_for_output(r"\[2\] Add\(100, 200\)", timeout=20)

@pytest.mark.needs_multicast
def test_rust_to_python_math_inst3(ctx):
    """Verify Rust client calls Python MathService (Instance 3)"""
    if ctx.get_runner("python") is None: pytest.skip("Python runner not available")
    if ctx.get_runner("rust") is None: pytest.skip("Rust runner not available")
    ctx.get_runner("python").clear_output()
    assert ctx.get_runner("python").wait_for_output(r"\[3\] Add\(10, 20\)", timeout=20)

@pytest.mark.needs_multicast
def test_cpp_rpc_to_math(ctx):
    """Verify C++ client calls MathService (Rust Instance 1)"""
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    if ctx.get_runner("rust") is None: pytest.skip("Rust runner not available")
    ctx.get_runner("cpp").clear_output()
    ctx.get_runner("rust").clear_output()
    assert ctx.get_runner("cpp").wait_for_output(r"Math\.Add Result:", timeout=10)
    assert ctx.get_runner("rust").wait_for_output("Math.Add", timeout=10)

@pytest.mark.needs_multicast
def test_cpp_event_updates(ctx):
    """Verify C++ SortService updates trigger events"""
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    ctx.get_runner("cpp").clear_output()
    assert ctx.get_runner("cpp").wait_for_output("Field 'status' changed", timeout=20)

@pytest.mark.needs_multicast
def test_rust_event_updates(ctx):
    """Verify Rust receives events from C++ SortService"""
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    if ctx.get_runner("rust") is None: pytest.skip("Rust runner not available")
    ctx.get_runner("rust").clear_output()
    assert ctx.get_runner("rust").wait_for_output("Received Notification", timeout=20)

@pytest.mark.needs_multicast
def test_python_to_cpp_sort(ctx):
    """Verify Python client calls C++ SortService"""
    if ctx.get_runner("python") is None: pytest.skip("Python runner not available")
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    ctx.get_runner("python").clear_output()
    ctx.get_runner("cpp").clear_output()
    assert ctx.get_runner("python").wait_for_output("Sending Sort...", timeout=10)
    assert ctx.get_runner("cpp").wait_for_output("Sorting 5 items", timeout=10)

@pytest.mark.needs_multicast
def test_rust_to_cpp_sort(ctx):
    """Verify Rust client calls C++ SortService"""
    if ctx.get_runner("cpp") is None: pytest.skip("CPP runner not available")
    ctx.get_runner("cpp").clear_output()
    assert ctx.get_runner("cpp").wait_for_output("Sorting 3 items", timeout=20)

@pytest.mark.needs_multicast
def test_js_rpc_to_rust(ctx):
    """Verify JS client calls Rust MathService"""
    if ctx.get_runner("js") is None: pytest.skip("JS runner not available")
    # Don't clear output; the JS runner might have finished before we got here
    # Use more specific regex to avoid consumption race
    assert ctx.get_runner("js").wait_for_output(r"Result: \d+", timeout=30)

@pytest.mark.needs_multicast
def test_js_rpc_to_python(ctx):
    """Verify JS client calls Python StringService"""
    if ctx.get_runner("js") is None: pytest.skip("JS runner not available")
    # Result: 'OLLEH'
    # Use more specific regex to avoid consumption race
    assert ctx.get_runner("js").wait_for_output(r"Result: '.*'", timeout=30)
