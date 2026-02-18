import sys
import os
import argparse
import time
import logging

# Add src/python to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src/python')))

from fusion_hawking.runtime import SomeIpRuntime

class LargePayloadClient:
    def __init__(self, config_path, instance_name="tp_client"):
        self.runtime = SomeIpRuntime(config_path, instance_name)
        self.log = logging.getLogger("tp_client")
        
    def run(self):
        self.runtime.start()
        
        try:
            # 1. Find Service
            service_id = 0x5000
            instance_id = 1
            major_version = 1
            
            self.log.info(f"Waiting for service 0x{service_id:04x}...")
            if not self.runtime.wait_for_service(service_id, instance_id, major_version, timeout=5):
                self.log.error("Service not found!")
                sys.exit(1)
                
            # Resolve Address
            addr = self.runtime.remote_services.get((service_id, major_version))
            if not addr:
                self.log.error("Service address not resolved!")
                sys.exit(1)
                
            self.log.info(f"Service found at {addr}! Sending Large Payload Request...")
            
            # 2. Send Large Payload (Echo)
            # 5000 bytes > 1400 MTU -> Should trigger TP
            import os
            payload = os.urandom(5000) 
            
            # Method 0x0002 is Echo
            response = self.runtime.send_request(service_id, 0x0002, payload, addr, wait_for_response=True, timeout=20)
            
            if response:
                if len(response) == 5000 and response == payload:
                    print("SUCCESS: ECHO Content Verified")
                else:
                    self.log.error(f"Response mismatch! Len={len(response)}")
                    if response != payload:
                        self.log.error("Data corruption detected: Received bytes do not match sent bytes.")
                    print("FAILURE: Content Mismatch")
                    sys.exit(1)
            else:
                self.log.error("No response received!")
                print("FAILURE: No Response")
                sys.exit(1)
                
            # 3. Send Get (Method 1)
            response = self.runtime.send_request(service_id, 0x0001, b'', addr, wait_for_response=True, timeout=20)
            if response and len(response) > 1400:
                print("SUCCESS: Content Verified (Get)")
            else:
                 self.log.error("Get Failed")

        finally:
            self.runtime.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", help="Path to configuration JSON")
    parser.add_argument("--instance", default="tp_client", help="Instance name in config")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG)
    
    client = LargePayloadClient(args.config_path, args.instance)
    client.run()
