import sys
import os
import time
import threading

# Path setup (points to root library and generated code)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'python'))

from fusion_hawking.runtime import SomeIpRuntime, RequestHandler
from runtime import IVersionedService_v1Stub, IVersionedService_v1Client, IVersionedService_v2Stub, IVersionedService_v2Client

class ServiceV1Impl(IVersionedService_v1Stub):
    def method_v1(self, x):
        print(f"[{self.__class__.__name__}] method_v1({x}) called")
        return x + 1

class ServiceV2Impl(IVersionedService_v2Stub):
    def method_v2(self, x, y):
        print(f"[{self.__class__.__name__}] method_v2({x}, {y}) called")
        return x + y

def run_server(instance_name, impl_cls):
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    runtime = SomeIpRuntime(config_path, instance_name)
    
    alias = "service_v1" if "v1" in instance_name else "service_v2"
    
    handler = impl_cls()
    runtime.start()
    runtime.offer_service(alias, handler)
    
    print(f"[{instance_name}] Service Offered (v{handler.MAJOR_VERSION})")
    
    try:
        while True: time.sleep(1)
    except:
        runtime.stop()

def run_client():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    runtime = SomeIpRuntime(config_path, "client")
    runtime.start()
    
    print("[Client] Discovery started...")
    
    # Discovery V1
    print("[Client] Waiting for V1...")
    client_v1 = runtime.get_client("service_v1", IVersionedService_v1Client, timeout=5.0)
    if client_v1:
        print(f"[Client] Found V1 Service (0x{client_v1.SERVICE_ID:04x} v{client_v1.MAJOR_VERSION})")
        try:
            res = client_v1.method_v1(10)
            print(f"[Client] V1 Call Result: {res}")
        except Exception as e:
            print(f"[Client] V1 Call Failed: {e}")
    else:
        print("[Client] Failed to find V1")

    # Discovery V2
    print("[Client] Waiting for V2...")
    client_v2 = runtime.get_client("service_v2", IVersionedService_v2Client, timeout=5.0)
    if client_v2:
        print(f"[Client] Found V2 Service (0x{client_v2.SERVICE_ID:04x} v{client_v2.MAJOR_VERSION})")
        try:
            res = client_v2.method_v2(10, 20)
            print(f"[Client] V2 Call Result: {res}")
        except Exception as e:
            print(f"[Client] V2 Call Failed: {e}")
    else:
        print("[Client] Failed to find V2")
        
    runtime.stop()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "server_v1":
            run_server("server_v1", ServiceV1Impl)
        elif sys.argv[1] == "server_v2":
            run_server("server_v2", ServiceV2Impl)
        elif sys.argv[1] == "client":
            run_client()
    else:
        print("Usage: python run.py [server_v1|server_v2|client]")
