import sys
import os
import time
import random

# Path setup (points to root library and generated code)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'python'))

from fusion_hawking import SomeIpRuntime, LogLevel, ConsoleLogger
from runtime import StringServiceStub, StringServiceClient, MathServiceClient, MathServiceStub, DiagnosticServiceStub, ComplexTypeServiceClient, SortServiceClient
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

class MathImpl(MathServiceStub):
    def __init__(self, logger, instance_id):
        self.logger = logger
        self.instance_id = instance_id
    def add(self, a, b):
        self.logger.log(LogLevel.INFO, "MathService", f"[{self.instance_id}] Add({a}, {b})")
        return a + b
    def sub(self, a, b):
        return a - b

def main():
    # Default config from parent directory
    default_config = os.path.join(os.path.dirname(__file__), "..", "config.json")
    logger = ConsoleLogger()
    logger.log(LogLevel.INFO, "Main", "=== Integrated Python Application ===")

    config_path = "examples/integrated_apps/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    rt = SomeIpRuntime(config_path, "python_app_instance", logger)
    rt.logger.log(LogLevel.INFO, "Main", f"--- Python Runtime Expanded Demo (Config: {config_path}) ---")
    rt.start()
    
    rt.offer_service("string-service", StringImpl(rt.logger))
    rt.offer_service("diagnostic-service", DiagImpl())
    rt.offer_service("math-service", MathImpl(rt.logger, 3))
    
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
