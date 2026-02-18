import os
import sys
import time
import pytest
from tools.fusion.environment import NetworkEnvironment
from tools.fusion.integration import IntegrationTestContext
from tools.fusion.config_gen import SmartConfigFactory
from tools.fusion.utils import to_wsl, find_binary

# Paths
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO_DIR = os.path.join(ROOT, "examples", "someipy_demo")

# Global environment
ENV = NetworkEnvironment()
if not ENV.interfaces:
    ENV.detect()

@pytest.fixture(scope="module")
def ctx():
    """Integration Test Context for REAL someipy interop tests"""
    factory = SmartConfigFactory(ENV)
    
    with IntegrationTestContext("test_someipy_interop") as c:
        # Generate someipy-specific config
        config_ret = factory.generate_someipy_demo(c.log_dir)
        
        if os.path.isdir(config_ret):
            # Distributed VNet
            daemon_config = to_wsl(os.path.join(config_ret, "config_ecu1.json"))
            client_config = to_wsl(os.path.join(config_ret, "config_ecu3.json"))
        else:
            # Single Config
            common = to_wsl(config_ret)
            daemon_config = common
            client_config = common

        # 1. Start someipy Daemon (on ECU1)
        daemon_cmd = [sys.executable, "-u", "start_daemon.py", daemon_config]
        c.add_runner("someipyd", daemon_cmd, cwd=DEMO_DIR, ns="ns_ecu1" if ENV.has_vnet else None).start()
        
        # 2. Start someipy Service (on ECU1)
        service_cmd = [sys.executable, "-u", "service_someipy.py", daemon_config]
        c.add_runner("someipy_svc", service_cmd, cwd=DEMO_DIR, ns="ns_ecu1" if ENV.has_vnet else None).start()
        
        # 3. Wait for service (someipy prints "Offering Service")
        svc = c.get_runner("someipy_svc")
        assert svc.wait_for_output("Offering Service", timeout=20)

        # 4. Start Fusion Clients (on ECU3)
        
        # Python Client
        py_src = os.path.join(ROOT, "src", "python")
        # For interop demo, we need someipy_demo bindings
        py_gen = os.path.join(ROOT, "build/generated/someipy_demo/python")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([to_wsl(py_src), to_wsl(py_gen)])
        
        py_client_cmd = [sys.executable, "-u", "client_fusion.py", client_config]
        c.add_runner("py_client", py_client_cmd, cwd=DEMO_DIR, env=env, ns="ns_ecu3" if ENV.has_vnet else None).start()
        
        # C++ Client
        cpp_exe = find_binary("client_fusion", search_dirs=[
            os.path.join(ROOT, "build", "examples", "someipy_demo"),
            os.path.join(ROOT, "build_linux", "examples", "someipy_demo"),
        ])
        if cpp_exe:
             c.add_runner("cpp_client", [cpp_exe, client_config, "cpp_client"], ns="ns_ecu3" if ENV.has_vnet else None).start()
        
        # JS Client
        js_client_dir = os.path.join(DEMO_DIR, "js_client")
        if os.path.exists(js_client_dir):
            c.add_runner("js_client", ["node", "dist/index.js", client_config], cwd=js_client_dir, ns="ns_ecu3" if ENV.has_vnet else None).start()

        time.sleep(5)
        yield c

def test_config_generation(ctx):
    """Verify that someipyd_config.json was generated in the log folder."""
    # Check directory of config_ecu1.json
    config_dir = ctx.log_dir
    internal_cfg = os.path.join(config_dir, "someipyd_config.json")
    assert os.path.exists(internal_cfg), f"Expected internal config at {internal_cfg}"

def test_python_client_interop(ctx):
    """Verify Fusion Python client can call someipy service."""
    runner = ctx.get_runner("py_client")
    assert runner.wait_for_output("Got Response", timeout=20)

def test_cpp_client_interop(ctx):
    """Verify Fusion C++ client can call someipy service."""
    runner = ctx.get_runner("cpp_client")
    if runner:
        assert runner.wait_for_output("Got Response", timeout=20)

def test_js_client_interop(ctx):
    """Verify Fusion JS client can call someipy service."""
    js_client_dir = os.path.join(DEMO_DIR, "js_client")
    js_dist = os.path.join(js_client_dir, "dist", "index.js")
    if not os.path.exists(js_dist):
        pytest.skip(f"JS client build missing at {js_dist}")

    runner = ctx.get_runner("js_client")
    if runner:
        assert runner.wait_for_output("Got Response:", timeout=20)
