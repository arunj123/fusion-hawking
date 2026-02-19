import os
import subprocess
import time
import pytest
import sys
import json
from fusion_hawking import SomeIpRuntime, LogLevel, ConsoleLogger

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from tools.fusion.utils import _get_env as get_environment

def generate_config(env, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "tcp_test_config.json")
    
    # Force loopback for this test as it relies on 127.0.0.1 hardcoded in original
    # But we should use env to be safe, though TCP test usually implies local.
    
    ipv4 = "127.0.0.1" # Force loopback for reliability in unit test
    iface_name = "Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo"
    
    config = {
        "interfaces": {
            "primary": {
                "name": iface_name,
                "endpoints": {
                    "sd_multicast": {
                        "ip": "224.0.0.5",
                        "port": 30890,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "server_tcp": {
                        "ip": ipv4,
                        "port": 0,
                        "version": 4,
                        "protocol": "tcp"
                    }
                },
                "sd": {
                    "endpoint": "sd_multicast"
                }
            }
        },
        "instances": {
            "tcp_server": {
                "providing": {
                    "math-service": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "major_version": 1,
                        "offer_on": {
                            "primary": "server_tcp"
                        }
                    }
                },
                "sd": {
                    "cycle_offer_ms": 100
                },
                "unicast_bind": {}
            },
            "tcp_client": {
                "required": {
                    "math-client": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "major_version": 1,
                        "find_on": [
                            "primary"
                        ]
                    }
                },
                "unicast_bind": {}
            }
        }
    }
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        
    return config_path

def test_tcp_transport_cpp_server():
    # Determine Log Dir
    log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "test_tcp"))
    os.makedirs(log_dir, exist_ok=True)
    
    env = get_environment()
    config_path = generate_config(env, log_dir)
    print(f"Generated config at: {config_path}")
    
    # Start C++ Server
    possible_paths = [
        os.path.abspath(os.path.join(PROJECT_ROOT, "build_wsl/Release/tcp_server_test")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "build_wsl/tcp_server_test")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "build_linux/tcp_server_test")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "build/Release/tcp_server_test.exe")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "build/Debug/tcp_server_test.exe")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "build/tcp_server_test.exe")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "build/tcp_server_test")),
    ]
    
    import platform
    is_windows = platform.system() == "Windows"
    
    server_exe = None
    for p in possible_paths:
        if is_windows and "build_wsl" in p:
            continue
        if is_windows and not p.lower().endswith(".exe"):
            continue
            
        if os.path.exists(p):
            server_exe = p
            break
            
    if not server_exe:
        print(f"ERROR: Could not find tcp_server_test executable. Searched in:")
        for p in possible_paths:
            print(f"  - {p}")
        pytest.fail("Could not find tcp_server_test executable. Make sure to build the project first.")
        
    print(f"DEBUG: Starting server: {server_exe} {config_path}")
    from tools.fusion.execution import AppRunner
    server = AppRunner("tcp_server", [server_exe, config_path], log_dir)
    server.start()

    try:
        # Wait for SD offer (AppRunner logs it)
        time.sleep(2)

        # Start Python Client
        os.environ["FUSION_PACKET_DUMP"] = "1"
        rt = SomeIpRuntime(config_path, "tcp_client", ConsoleLogger())
        rt.start()

        # Wait for SD discovery
        service_found = False
        for _ in range(50):
            if any(k[0] == 4097 for k in rt.remote_services.keys()):
                service_found = True
                break
            time.sleep(0.1)

        if not service_found:
             # Check if server is still running
             if not server.is_running():
                 print(f"Server died with code {server.get_return_code()}")
             assert False, "Service 4097 not discovered over TCP/SD"

        # Send Request
        service_key = next(k for k in rt.remote_services.keys() if k[0] == 4097)
        target_addr = rt.remote_services[service_key]
        print(f"[Python Client] Discovered service 4097 at {target_addr}")
        payload = bytes([0, 0, 0, 10, 0, 0, 0, 20]) # 10 + 20
        response = rt.send_request(service_key[0], 1, payload, target_addr, wait_for_response=True)

        assert response is not None, "No response received over TCP"
        assert len(response) >= 4, "Response payload too short"

        res_val = (response[0] << 24) | (response[1] << 16) | (response[2] << 8) | response[3]
        assert res_val == 30, f"Expected 30, got {res_val}"

        print(f"[Python Client] Result: {res_val} (Success!)")

    except Exception as e:
        print(f"Test Failed: {e}")
        server.stop()
        # Read the log file created by AppRunner
        if os.path.exists(server.log_path):
            with open(server.log_path, 'r') as f:
                print("--- Server Logs ---")
                print(f.read())
        raise e
    finally:
        server.stop()
        rt.stop()

if __name__ == "__main__":
    test_tcp_transport_cpp_server()
