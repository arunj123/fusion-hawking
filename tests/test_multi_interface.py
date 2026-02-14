import sys
import os
import time
import threading
import json

# Add src/python to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "python")))

from fusion_hawking import SomeIpRuntime, RequestHandler, ConsoleLogger, LogLevel

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

def run_service():
    config_path = os.path.join(os.path.dirname(__file__), "multi_interface_config.json")
    runtime = SomeIpRuntime(config_path, "ServiceNode")
    runtime.offer_service("MathService", MathHandler())
    runtime.start()
    print("[Service] Started on iface1")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        runtime.stop()

def run_client():
    config_path = os.path.join(os.path.dirname(__file__), "multi_interface_config.json")
    runtime = SomeIpRuntime(config_path, "ClientNode")
    runtime.start()
    print("[Client] Started on iface2 & iface1")
    
    # Wait for discovery
    client = runtime.get_client("MathService", None, timeout=10.0)
    if client:
        print("[Client] Discovered MathService!")
        # Test RPC
        res = runtime.send_request(4097, 1, bytes([10, 20]), runtime.remote_services[(4097, 1)], wait_for_response=True)
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
    if len(sys.argv) > 1 and sys.argv[1] == "service":
        run_service()
    elif len(sys.argv) > 1 and sys.argv[1] == "client":
        run_client()
    else:
        # Run both in subprocesses or threads
        t1 = threading.Thread(target=run_service, daemon=True)
        t1.start()
        time.sleep(2)
        run_client()
