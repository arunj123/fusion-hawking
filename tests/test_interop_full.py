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

# Global environment
ENV = NetworkEnvironment()
if not ENV.interfaces:
    ENV.detect()

py_src = os.path.join(ROOT, "src", "python")

@pytest.fixture(scope="module")
def ctx():
    """Integration Test Context for interop tests"""
    factory = SmartConfigFactory(ENV)
    
    with IntegrationTestContext("test_interop_full") as c:
        # SmartConfigFactory handles all interface/IP resolution
        config_ret = factory.generate_someipy_demo(c.log_dir)
        
        if os.path.isdir(config_ret):
            # Distributed VNet
            service_config = to_wsl(os.path.join(config_ret, "config_ecu1.json"))
            client_config = to_wsl(os.path.join(config_ret, "config_ecu3.json"))
        else:
            # Single Config
            common = to_wsl(config_ret)
            service_config = common
            client_config = common

        # 1. Start Python someipy Service (Mock/Demo)
        service_code = f"""
import sys, time, os
sys.path.append(r'{to_wsl(py_src)}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler
class Handler(RequestHandler):
    def get_service_id(self): return 0x1234
    def handle(self, mi, p):
        print(f"MOCK_RECEIVED: {{p.decode()}}")
        return b"Response from Python!"
rt = SomeIpRuntime(r'{service_config}', 'PythonService')
rt.offer_service('someipy_svc', Handler())
rt.start()
print("MOCK_READY")
sys.stdout.flush()
while True: time.sleep(1)
"""
        c.run_python_code(service_code, "python_service", ns="ns_ecu1" if ENV.has_vnet else None)
        
        # 2. Wait for service to be ready
        srv = c.get_runner("python_service")
        assert srv.wait_for_output("MOCK_READY", timeout=10)

        # 3. Start Clients
        
        # C++ Client
        cpp_exe = find_binary("client_fusion", search_dirs=[
            os.path.join(ROOT, "build_linux", "examples", "someipy_demo"),
            os.path.join(ROOT, "build", "Release"),
            os.path.join(ROOT, "examples", "someipy_demo", "build", "Release"),
            os.path.join(ROOT, "examples", "someipy_demo", "build"),
        ])
        if cpp_exe:
             c.add_runner("cpp_client", [cpp_exe, client_config, "cpp_client"], ns="ns_ecu3" if ENV.has_vnet else None).start()
             time.sleep(1)
        
        # JS Client
        c.add_runner("js_client", ["node", "tests/interop_client.mjs", client_config], cwd=ROOT, ns="ns_ecu3" if ENV.has_vnet else None, env={"FUSION_PACKET_DUMP": "1"}).start()
        time.sleep(1)

        # Rust Client
        rust_bin = find_binary("someipy_client", search_dirs=[
            os.path.join(ROOT, "examples", "someipy_demo", "target", "debug"),
            os.path.join(ROOT, "examples", "someipy_demo", "target", "release"),
        ])
        if rust_bin:
            c.add_runner("rust_client", [rust_bin, client_config, "rust_client"], cwd=ROOT, ns="ns_ecu3" if ENV.has_vnet else None).start()
            time.sleep(1)

        time.sleep(5)
        yield c

def test_cpp_interop(ctx):
    """Verify C++ client interop with Python service."""
    runner = ctx.get_runner("cpp_client")
    if runner:
        assert runner.wait_for_output("Got Response: 'Response from Python!'", timeout=20)

def test_js_interop(ctx):
    """Verify JS client interop with Python service."""
    runner = ctx.get_runner("js_client")
    assert runner.wait_for_output("Got Response: Response from Python!", timeout=20)

def test_rust_interop(ctx):
    """Verify Rust client interop with Python service."""
    runner = ctx.get_runner("rust_client")
    if runner:
        assert runner.wait_for_output("Got Response: 'Response from Python!'", timeout=20)

if __name__ == "__main__":
    pytest.main([__file__, "-s"])
