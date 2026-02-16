import subprocess
import time
import os
import sys
import pytest

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
    """Integration Test Context for Automotive PubSub demo.
    """
    factory = SmartConfigFactory(ENV)
    
    # ECU1: Radar (C++), ECU2: Fusion (Rust), ECU3: ADAS (Py/JS)
    ns_radar = "ns_ecu1" if ENV.has_vnet else None
    ns_fusion = "ns_ecu2" if ENV.has_vnet else None
    ns_adas = "ns_ecu3" if ENV.has_vnet else None
    
    with IntegrationTestContext("test_pubsub_full") as c:
        config_ret = factory.generate_automotive_pubsub(c.log_dir)
        
        if os.path.isdir(config_ret):
            # Distributed VNet (3 ECUs)
            radar_config = to_wsl(os.path.join(config_ret, "config_ecu1.json"))
            fusion_config = to_wsl(os.path.join(config_ret, "config_ecu2.json"))
            adas_config = to_wsl(os.path.join(config_ret, "config_ecu3.json"))
        else:
            # Single Config
            common = to_wsl(os.path.abspath(config_ret))
            radar_config = common
            fusion_config = common
            adas_config = common
        
        # 1. Radar (C++ ECU1)
        radar_exe = find_binary("radar_demo", search_dirs=[
            os.path.join(PROJECT_ROOT, "build_linux", "examples", "automotive_pubsub", "cpp_radar"),
            os.path.join(PROJECT_ROOT, "build_wsl", "examples", "automotive_pubsub", "cpp_radar"),
            os.path.join(PROJECT_ROOT, "build", "examples", "automotive_pubsub", "cpp_radar", "Release"),
            os.path.join(PROJECT_ROOT, "examples", "automotive_pubsub", "cpp_radar", "build", "Release"),
            os.path.join(PROJECT_ROOT, "build", "examples", "automotive_pubsub", "cpp_radar"),
        ])
        if radar_exe:
             c.add_runner("radar", [radar_exe, radar_config], ns=ns_radar).start()
             time.sleep(1)
        
        # 2. Fusion (Rust ECU2)
        fusion_dir = os.path.join(PROJECT_ROOT, "examples", "automotive_pubsub", "rust_fusion")
        fusion_bin = find_binary("fusion_node", search_dirs=[
            os.path.join(fusion_dir, "target", "debug"),
            os.path.join(fusion_dir, "target", "release"),
        ])
        if fusion_bin:
            c.add_runner("fusion", [fusion_bin, fusion_config], cwd=fusion_dir, ns=ns_fusion).start()
            time.sleep(1)
 
        # 3. Python ADAS (ECU3)
        adas_py_dir = os.path.join(PROJECT_ROOT, "examples", "automotive_pubsub", "python_adas")
        env = os.environ.copy() 
        env["PYTHONPATH"] = os.pathsep.join([os.path.join(PROJECT_ROOT, "src", "python"), 
                                            os.path.join(PROJECT_ROOT, "build"),
                                            os.path.join(PROJECT_ROOT, "build", "generated", "python")])
        c.add_runner("adas_py", [sys.executable, "-u", "main.py", adas_config], cwd=adas_py_dir, env=env, ns=ns_adas).start()
 
        # 4. JS ADAS (ECU3)
        adas_js_dir = os.path.join(PROJECT_ROOT, "examples", "automotive_pubsub", "js_adas")
        if os.path.exists(adas_js_dir):
            npm_bin = "npm.cmd" if os.name == 'nt' else "npm"
            if not os.path.exists(os.path.join(adas_js_dir, "dist", "index.js")):
                 subprocess.run([npm_bin, "install"], cwd=adas_js_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 subprocess.run([npm_bin, "run", "build"], cwd=adas_js_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            c.add_runner("adas_js", ["node", "dist/index.js", adas_config], cwd=adas_js_dir, ns=ns_adas).start()

        time.sleep(5)
        yield c

def has_multicast_support():
    return os.name != 'nt'

@pytest.mark.needs_multicast
def test_radar_publishing(ctx):
    """Verify Radar is publishing objects"""
    if ctx.get_runner("radar") is None: pytest.skip("Radar binary not found")
    assert ctx.get_runner("radar").wait_for_output("Publishing", timeout=20)

@pytest.mark.needs_multicast
def test_fusion_events(ctx):
    """Verify Fusion node receives data and publishes tracks"""
    if ctx.get_runner("fusion") is None: pytest.skip("Fusion binary not found")
    # Radar -> Fusion: Fused X tracks
    assert ctx.get_runner("fusion").wait_for_output("Fused", timeout=30)
    assert ctx.get_runner("fusion").wait_for_output("Publishing", timeout=30)

@pytest.mark.needs_multicast
def test_adas_py_output(ctx):
    """Verify Python ADAS receives fused tracks"""
    # ADAS: Received X fused tracks
    assert ctx.get_runner("adas_py").wait_for_output("Received", timeout=30)

@pytest.mark.needs_multicast
def test_adas_js_output(ctx):
    """Verify JS ADAS receives fused tracks"""
    if ctx.get_runner("adas_js") is None: pytest.skip("JS ADAS not available")
    assert ctx.get_runner("adas_js").wait_for_output("Received", timeout=30)
