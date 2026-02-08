import os
import subprocess
import time
import pytest
import sys
from fusion_hawking import SomeIpRuntime, LogLevel

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)
from tools.fusion.utils import patch_configs

def setup_module(module):
    """Patch configuration to use loopback for safe local testing"""
    print("DEBUG: Patching configs to force loopback for TCP transport tests...")
    patch_configs(ip_v4="127.0.0.1", root_dir=PROJECT_ROOT, ip_v6="::1")

def test_tcp_transport_cpp_server():
    config_path = os.path.abspath("tests/tcp_test_config.json")
    
    # Start C++ Server
    possible_paths = [
        os.path.abspath("build/Release/tcp_server_test.exe"),
        os.path.abspath("build/Debug/tcp_server_test.exe"),
        os.path.abspath("build/tcp_server_test.exe"),
        os.path.abspath("build/tcp_server_test"),
        os.path.abspath("build_wsl/tcp_server_test"),
        os.path.abspath("build_wsl/Release/tcp_server_test"),
        os.path.abspath("build_cpp_debug/Release/tcp_server_test.exe"), # Legacy
        os.path.abspath("build_cpp_debug/tcp_server_test") # Legacy
    ]
    
    server_exe = None
    for p in possible_paths:
        if os.path.exists(p):
            server_exe = p
            break
            
    if not server_exe:
        pytest.fail("Could not find tcp_server_test executable. Make sure to build the project first.")
        
    print(f"DEBUG: Starting server: {server_exe} {config_path}")
    server_proc = subprocess.Popen([server_exe, config_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    try:
        # Wait for SD offer
        time.sleep(2)
        
        # Start Python Client
        logger = None # Default logger
        rt = SomeIpRuntime(config_path, "tcp_client", logger)
        rt.start()
        
        # Wait for SD discovery
        service_found = False
        for _ in range(50):
            if 4097 in rt.remote_services:
                service_found = True
                break
            time.sleep(0.1)
        
        assert service_found, "Service 4097 not discovered over TCP/SD"
        
        # Send Request
        target_addr = rt.remote_services[4097]
        print(f"[Python Client] Discovered service 4097 at {target_addr}")
        payload = bytes([0, 0, 0, 10, 0, 0, 0, 20]) # 10 + 20
        response = rt.send_request(4097, 1, payload, target_addr, wait_for_response=True)
        
        if response is None:
             print("[Python Client] ERROR: send_request returned None")
        
        assert response is not None, "No response received over TCP"
        assert len(response) >= 4, "Response payload too short"
        
        res_val = (response[0] << 24) | (response[1] << 16) | (response[2] << 8) | response[3]
        assert res_val == 30, f"Expected 30, got {res_val}"
        
        print(f"[Python Client] Result: {res_val} (Success!)")
        
    except Exception as e:
        print(f"Test Failed: {e}")
        # Print server output
        if server_proc.poll() is not None:
            print(f"Server exited with {server_proc.returncode}")
        
        # We need to read remaining output. Since we used PIPE, we can't easily read without blocking or threads if it's still running.
        # But if we terminate it, we can read.
        server_proc.terminate()
        try:
            outs, errs = server_proc.communicate(timeout=2)
            print("--- Server Stdout ---")
            print(outs)
            print("--- Server Stderr ---")
            print(errs)
        except:
            print("Could not get server output")
        raise e
    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait()

if __name__ == "__main__":
    test_tcp_transport_cpp_server()
