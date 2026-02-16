import time
import os
import pytest
from tools.fusion.integration import IntegrationTestContext
from tools.fusion.utils import find_binary

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

@pytest.fixture(scope="module")
def ctx():
    """Integration Test Context for simple UDP demo.
    """
    with IntegrationTestContext("test_simple_demo") as c:
        # 1. Simple Server
        server_bin = find_binary("simple_server", search_dirs=[
            os.path.join(PROJECT_ROOT, "target", "debug"),
            os.path.join(PROJECT_ROOT, "target", "release"),
            os.path.join(PROJECT_ROOT, "build", "examples", "simple"),
            os.path.join(PROJECT_ROOT, "build_linux", "examples", "simple"),
        ])
        if server_bin:
            c.add_runner("server", [server_bin]).start()
        
        # 2. Simple Client
        client_bin = find_binary("simple_client", search_dirs=[
            os.path.join(PROJECT_ROOT, "target", "debug"),
            os.path.join(PROJECT_ROOT, "target", "release"),
            os.path.join(PROJECT_ROOT, "build", "examples", "simple"),
            os.path.join(PROJECT_ROOT, "build_linux", "examples", "simple"),
        ])
        if client_bin:
            # We run client as a runner but it's expected to finish
            c.add_runner("client", [client_bin]).start()
        
        time.sleep(2)
        yield c

def test_simple_server_startup(ctx):
    if ctx.get_runner("server") is None: pytest.skip("Server binary not found")
    assert ctx.get_runner("server").wait_for_output("Simple Server listening", timeout=10)

def test_simple_client_success(ctx):
    if ctx.get_runner("client") is None: pytest.skip("Client binary not found")
    # Client should output "Success: Got Response!"
    assert ctx.get_runner("client").wait_for_output("Success", timeout=10)
    assert ctx.get_runner("server").wait_for_output("Received", timeout=10)
