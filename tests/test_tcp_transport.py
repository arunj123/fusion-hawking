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
        pytest.fail("Could not find tcp_server_test executable. Make sure to build the project first.")
        
    print(f"DEBUG: Starting server: {server_exe} {config_path}")
    server_proc = subprocess.Popen([server_exe, config_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    try:
        # Wait for SD offer
        time.sleep(2)
        
        # Start Python Client
        os.environ["FUSION_PACKET_DUMP"] = "1"
        rt = SomeIpRuntime(config_path, "tcp_client", ConsoleLogger())
        rt.start()
        
        # Wait for SD discovery
        service_found = False
        for _ in range(50):
            # rt.remote_services keys are (service_id, major_version)
            if any(k[0] == 4097 for k in rt.remote_services.keys()):
                service_found = True
                break
            time.sleep(0.1)
        
        assert service_found, "Service 4097 not discovered over TCP/SD"
        
        # Send Request
        # Find the specific key for 4097
        service_key = next(k for k in rt.remote_services.keys() if k[0] == 4097)
        target_addr = rt.remote_services[service_key]
        print(f"[Python Client] Discovered service 4097 at {target_addr}")
        payload = bytes([0, 0, 0, 10, 0, 0, 0, 20]) # 10 + 20
        # send_request(service_id, method_id, payload, endpoint, wait_for_response)
        response = rt.send_request(service_key[0], 1, payload, target_addr, wait_for_response=True)
        
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
