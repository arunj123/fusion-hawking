import sys
import os
import time

# Ensure src is in path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from generated.runtime import SomeIpRuntime
from generated.bindings import StringServiceStub, MathServiceClient

class StringImpl(StringServiceStub):
    def reverse(self, s):
        print(f"Server: Reversing '{s}'")
        return s[::-1]

def main():
    print("--- High-Level Python Runtime Demo ---")
    
    # 1. Initialize Runtime
    rt = SomeIpRuntime("examples/config.json", "python_app_instance")
    
    # 2. Offer Service with Alias
    rt.offer_service("string-service", StringImpl())
    
    # 3. Client Logic
    client = rt.get_client("math-client", MathServiceClient)
    
    try:
        while True:
            print("Python Client: Sending Add(10, 20)...")
            client.add(10, 20)
            time.sleep(2)
    except KeyboardInterrupt:
        print("Stopping...")

if __name__ == "__main__":
    main()
