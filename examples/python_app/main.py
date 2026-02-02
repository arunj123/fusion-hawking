import sys
import os
import time

# Ensure build/generated/python is in path
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))
# Ensure src/python is in path for the core library
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))

from runtime import SomeIpRuntime, StringServiceStub, StringServiceClient, MathServiceClient, LogLevel
from bindings import *

class StringImpl(StringServiceStub):
    def __init__(self, logger):
        self.logger = logger
    def reverse(self, s):
        self.logger.log(LogLevel.DEBUG, "StringService", f"Reversing '{s}'")
        return s[::-1]

def main():
    # 1. Initialize Runtime
    rt = SomeIpRuntime("examples/config.json", "python_app_instance")
    # Logger uses default level
    rt.logger.log(LogLevel.INFO, "Main", "--- High-Level Python Runtime Demo ---")
    rt.start()
    
    # 2. Offer Service with Alias
    rt.offer_service("string-service", StringImpl(rt.logger))
    
    # 3. Client Logic
    # 3. Client Logic
    client = None
    while client is None:
        try:
            client = rt.get_client("math-client", MathServiceClient, timeout=1.0)
            if client is None:
                rt.logger.log(LogLevel.INFO, "Main", "Waiting for MathService...")
        except KeyboardInterrupt:
            return

    # Loop for logic
    # Loop for logic
    try:
        while True:
            rt.logger.log(LogLevel.INFO, "Main", "Client: Sending Add(10, 20)...")
            client.add(10, 20)
            
            # Test calling itself
            string_client = rt.get_client("string-client", StringServiceClient)
            if string_client:
                string_client.reverse("Loopback")
            
            time.sleep(2)
    except KeyboardInterrupt:
        rt.logger.log(LogLevel.INFO, "Main", "Stopping...")
    finally:
        rt.stop()

if __name__ == "__main__":
    main()
