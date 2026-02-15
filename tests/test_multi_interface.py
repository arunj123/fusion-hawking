import sys
import os
import time
import threading
import json
import shutil

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from tools.fusion.utils import _get_env as get_environment

# Add src/python to sys.path
sys.path.append(os.path.join(PROJECT_ROOT, "src", "python"))

from fusion_hawking import SomeIpRuntime, RequestHandler, ConsoleLogger, LogLevel

def generate_config(output_dir):
    """Generate multi-interface configuration."""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "multi_interface_config.json")
    
    # Use detected loopback name
    iface_name = "Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo"
    
    config = {
        "interfaces": {
            "iface1": {
                "name": iface_name,
                "sd": {
                    "endpoint_v4": "sd_mcast1"
                },
                "endpoints": {
                    "sd_mcast1": {
                        "ip": "224.0.0.1",
                        "port": 30491,
                        "protocol": "udp",
                        "version": 4
                    },
                    "service_ep": {
                        "ip": "127.0.0.1",
                        "port": 40001,
                        "protocol": "udp",
                        "version": 4
                    },
                    "client_ep1": {
                        "ip": "127.0.0.1",
                        "port": 40101,
                        "protocol": "udp",
                        "version": 4
                    },
                    "sd_bind_svc": {
                        "ip": "127.0.0.1",
                        "port": 0,
                        "protocol": "udp",
                        "version": 4
                    },
                    "sd_bind_client": {
                        "ip": "127.0.0.1",
                        "port": 0,
                        "protocol": "udp",
                        "version": 4
                    }
                }
            },
            "iface2": {
                "name": iface_name,
                "sd": {
                    "endpoint_v4": "sd_mcast2"
                },
                "endpoints": {
                    "sd_mcast2": {
                        "ip": "224.0.0.2",
                        "port": 30492,
                        "protocol": "udp",
                        "version": 4
                    },
                    "client_ep2": {
                        "ip": "127.0.0.1",
                        "port": 40102,
                        "protocol": "udp",
                        "version": 4
                    },
                    "sd_bind_client": {
                        "ip": "127.0.0.1",
                        "port": 0,
                        "protocol": "udp",
                        "version": 4
                    }
                }
            }
        },
        "instances": {
            "ServiceNode": {
                "providing": {
                    "MathService": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "major_version": 1,
                        "offer_on": {
                            "iface1": "service_ep"
                        }
                    }
                },
                "unicast_bind": {
                    "iface1": "sd_bind_svc"
                }
            },
            "ClientNode": {
                "required": {
                    "MathService": {
                        "service_id": 4097,
                        "major_version": 1,
                        "find_on": [
                            "iface1",
                            "iface2"
                        ]
                    }
                },
                "unicast_bind": {
                    "iface1": "sd_bind_client",
                    "iface2": "sd_bind_client"
                }
            }
        }
    }
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        
    return config_path

class MathHandler(RequestHandler):
    def get_service_id(self): return 4097
    def get_instance_id(self): return 1
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, method_info, payload):
        if method_info['method_id'] == 1: # Add (simplified)
            a, b = payload[0], payload[1]
            return bytes([a + b])
        return None

def run_service(config_path):
    print(f"[Service] Using config: {config_path}")
    runtime = SomeIpRuntime(config_path, "ServiceNode")
    runtime.offer_service("MathService", MathHandler())
    runtime.start()
    print("[Service] Started on iface1")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        runtime.stop()

def run_client(config_path):
    print(f"[Client] Using config: {config_path}")
    runtime = SomeIpRuntime(config_path, "ClientNode")
    runtime.start()
    print("[Client] Started on iface2 & iface1")
    
    # Wait for discovery
    client = runtime.get_client("MathService", None, timeout=10.0)
    if client:
        print("[Client] Discovered MathService!")
        # Test RPC
        # Note: remote_services keys are (service_id, major_version)
        target_addr = runtime.remote_services.get((4097, 1))
        if not target_addr:
             # Try finding ANY
             for k, v in runtime.remote_services.items():
                 if k[0] == 4097:
                     target_addr = v
                     break
        
        if not target_addr:
            print("[Client] Service discovered but endpoint not found in remote_services?")
            os._exit(1)

        res = runtime.send_request(4097, 1, bytes([10, 20]), target_addr, wait_for_response=True)
        if res and res[0] == 30:
            print("[Client] RPC Success: 10 + 20 = 30")
            os._exit(0)
        else:
            print(f"[Client] RPC Failed: {res}")
            os._exit(1)
    else:
        print("[Client] Discovery Timeout")
        os._exit(1)

if __name__ == "__main__":
    # Generate Config
    log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "test_multi_interface"))
    config_path = generate_config(log_dir)
    
    if len(sys.argv) > 1 and sys.argv[1] == "service":
        run_service(config_path)
    elif len(sys.argv) > 1 and sys.argv[1] == "client":
        run_client(config_path)
    else:
        # Run both in subprocesses or threads
        t1 = threading.Thread(target=run_service, args=(config_path,), daemon=True)
        t1.start()
        time.sleep(2)
        run_client(config_path)
