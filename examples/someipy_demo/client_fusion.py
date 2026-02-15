import sys
import os
import time

# Add src/python to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src/python")))

from fusion_hawking.runtime import SomeIpRuntime, RequestHandler
try:
    from common_ids import SOMEIPY_SERVICE_ID, SOMEIPY_METHOD_ECHO
except ImportError:
    sys.path.append(os.path.dirname(__file__))
    from common_ids import SOMEIPY_SERVICE_ID, SOMEIPY_METHOD_ECHO

class GenericClient:
    SERVICE_ID = SOMEIPY_SERVICE_ID
    
    def __init__(self, runtime, alias):
        self.runtime = runtime
        self.alias = alias
        
    def echo(self, message):
        payload = message.encode('utf-8')
        # Method ID from common_ids
        # Access remote_services with (SID, MajorVersion) tuple. Assuming v1.
        target_addr = self.runtime.remote_services.get((self.SERVICE_ID, 1))
        
        if not target_addr:
             # Try legacy/int key just in case (though runtime fixed)
             remote = self.runtime.remote_services
             # scan for matching service ID
             for k, v in remote.items():
                 if isinstance(k, tuple) and k[0] == self.SERVICE_ID:
                     target_addr = v
                     break
        
        if not target_addr:
             print("Error: Service not found in remote_services")
             return None

        response = self.runtime.send_request(
            self.SERVICE_ID, 
            SOMEIPY_METHOD_ECHO, 
            payload, 
            target_addr, 
            msg_type=0x00, # Request
            wait_for_response=True
        )
        return response

def main():
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(os.path.dirname(__file__), "client_config.json")
    
    # Create client_config.json if missing (simplified fallback)
    if not os.path.exists(config_path):
        print(f"Error: custom config missing at {config_path}")
        return

    runtime = SomeIpRuntime(config_path, "python_client")
    runtime.start()
    
    print(f"[Fusion Python Client] Waiting for someipy service ({hex(SOMEIPY_SERVICE_ID)})...")
    # Timeout 10s to be safe
    client = runtime.get_client("someipy_svc", GenericClient, timeout=10.0)
    
    if client:
        message = "Hello from Fusion Python!"
        print(f"[Fusion Python Client] Sending Echo: '{message}'")
        
        response = client.echo(message)
        
        if response:
            print(f"[Fusion Python Client] Got Response: '{response.decode()}'")
        else:
            print("[Fusion Python Client] Failed to get response.")
    else:
        print("[Fusion Python Client] Could not discover service.")
        
    runtime.stop()

if __name__ == "__main__":
    main()
