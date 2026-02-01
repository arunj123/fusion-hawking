import sys
import os
import time

# Ensure build/generated/python is in path
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))

from runtime import SomeIpRuntime
from bindings import StringServiceStub, MathServiceClient

class StringImpl(StringServiceStub):
    def reverse(self, s):
        print(f"[PYTHON] Server: Reversing '{s}'")
        return s[::-1]

def main():
    print("[PYTHON] --- High-Level Python Runtime Demo ---")
    
    # 1. Initialize Runtime
    rt = SomeIpRuntime("examples/config.json", "python_app_instance")
    
    # 2. Offer Service with Alias
    rt.offer_service("string-service", StringImpl())
    
    # 3. Client Logic
    client = rt.get_client("math-client", MathServiceClient)
    
    try:
        while True:
            print("[PYTHON] Client: Sending Add(10, 20)...")
            client.add(10, 20)
            time.sleep(2)
    except KeyboardInterrupt:
        print("[PYTHON] Stopping...")

if __name__ == "__main__":
    main()
