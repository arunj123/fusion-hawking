import os
import subprocess
import time
import pytest
from fusion_hawking import SomeIpRuntime, LogLevel

def test_tcp_transport_cpp_server():
    config_path = os.path.abspath("tests/tcp_test_config.json")
    
    # Start C++ Server
    possible_paths = [
        os.path.abspath("build/Release/tcp_server_test.exe"),
        os.path.abspath("build/Debug/tcp_server_test.exe"),
        os.path.abspath("build/tcp_server_test.exe"),
        os.path.abspath("build/tcp_server_test"),
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
        payload = bytes([0, 0, 0, 10, 0, 0, 0, 20]) # 10 + 20
        response = rt.send_request(4097, 1, payload, target_addr, wait_for_response=True)
        
        assert response is not None, "No response received over TCP"
        assert len(response) >= 4, "Response payload too short"
        
        res_val = (response[0] << 24) | (response[1] << 16) | (response[2] << 8) | response[3]
        assert res_val == 30, f"Expected 30, got {res_val}"
        
        print(f"[Python Client] Result: {res_val} (Success!)")
        
    finally:
        server_proc.terminate()
        server_proc.wait()

if __name__ == "__main__":
    test_tcp_transport_cpp_server()
