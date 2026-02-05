import sys
import os
import time
import random

# Path setup
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))

from runtime import SomeIpRuntime, StringServiceStub, StringServiceClient, MathServiceClient, DiagnosticServiceStub, ComplexTypeServiceClient, SortServiceClient, LogLevel
from bindings import *


class StringImpl(StringServiceStub):
    def __init__(self, logger):
        self.logger = logger
    def reverse(self, text):
        self.logger.log(LogLevel.INFO, "StringService", f"Reversing '{text}'")
        return text[::-1]
    def uppercase(self, text):
        return text.upper()

class DiagImpl(DiagnosticServiceStub):
    def get_version(self):
        return "1.2.3-py"
    def run_self_test(self, level):
        return True

def main():
    rt = SomeIpRuntime("examples/integrated_apps/config.json", "python_app_instance")
    rt.logger.log(LogLevel.INFO, "Main", "--- Python Runtime Expanded Demo ---")
    rt.start()
    
    rt.offer_service("string-service", StringImpl(rt.logger))
    rt.offer_service("diagnostic-service", DiagImpl())
    
    time.sleep(2)
    
    try:
        while True:
            # Client Calls
            math = rt.get_client("math-client", MathServiceClient)
            if math:
                rt.logger.log(LogLevel.INFO, "Client", "Sending Add...")
                math.add(random.randint(0, 50), random.randint(0, 50))
            
            sort_svc = rt.get_client("sort-client", SortServiceClient)
            if sort_svc:
                rt.logger.log(LogLevel.INFO, "Client", "Sending Sort...")
                sort_svc.sort_asc([5, 3, 1, 4, 2])

            complex_svc = rt.get_client("complex-client", ComplexTypeServiceClient)
            if complex_svc:
                complex_svc.check_health()
                
                # Test complex type
                status = SystemStatus(
                    uptime=int(time.time()),
                    devices=[
                        DeviceInfo(id=101, name="PySensor", is_active=True, firmware_version="2.0")
                    ],
                    cpu_load=0.5
                )
                complex_svc.update_system_status(status)
            
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop()

if __name__ == "__main__":
    main()
