import json
import os
import sys

import importlib.util

interface_path = os.path.join(os.getcwd(), 'examples', 'interface.py')
if not os.path.exists(interface_path):
    print(f"Error: {interface_path} does not exist.")
    sys.exit(1)

import importlib.util
import inspect

interface_path = os.path.join(os.getcwd(), 'examples', 'interface.py')
if not os.path.exists(interface_path):
    print(f"Error: {interface_path} does not exist.")
    sys.exit(1)

spec = importlib.util.spec_from_file_location("interface", interface_path)
interface = importlib.util.module_from_spec(spec)
spec.loader.exec_module(interface)

# Find all classes with is_service attribute
services = [obj for name, obj in inspect.getmembers(interface) if inspect.isclass(obj) and getattr(obj, 'is_service', False)]

CONFIG_PATH = "examples/config.json"

def generate_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: {CONFIG_PATH} does not exist.")
        return

    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    # Helper map: Service Name -> Service Object
    service_map = {s.__name__: s for s in services}

    # Update instances
    for instance_name, instance_data in config.get("instances", {}).items():
        # Update Provided Services
        for svc_alias, svc_data in instance_data.get("providing", {}).items():
            # Match strictly by alias if it matches service name, or try to infer
            # Infer logic: alias usually contains service name.
            # For this demo, let's look for exact name match in interface or mapped name
            target_svc = None
            if svc_alias in service_map:
                target_svc = service_map[svc_alias]
            else:
                 # Try to find if alias contains any service name
                 for sname, s in service_map.items():
                     if sname in svc_alias: # e.g. "math-service" contains "math" (if named 'math') - interface names are 'MathService' etc.
                         # interface.py names are TitleCase (MathService). aliases are kebab-case.
                         pass
            
            # Better approach: Check if svc_data has a service_id, if so, we can't really update it unless we know the name
            # Let's rely on the alias matching the service name converted to kebab-case or just map known ones.
            # Actually, the user wants us to Generate the service related part.
            # We can map:
            # "math-service" -> MathService
            # "complex-service" -> ComplexTypeService
            # "string-service" -> StringService
            # "diagnostic-service" -> DiagnosticService
            # "sort-service" -> SortService
            # "sensor-service" -> SensorService
            
            # Simple Mapping for this demo
            svc_name_map = {
                "math-service": "MathService",
                "math-client": "MathService",
                "complex-service": "ComplexTypeService",
                "complex-client": "ComplexTypeService",
                "string-service": "StringService",
                "string-client": "StringService",
                "diagnostic-service": "DiagnosticService",
                "diag-client": "DiagnosticService",
                "sort-service": "SortService",
                "sort-client": "SortService",
                "sensor-service": "SensorService",
            }

            key_sv = svc_name_map.get(svc_alias)
            if key_sv and key_sv in service_map:
                s = service_map[key_sv]
                if hasattr(s, 'service_id'):
                    svc_data["service_id"] = s.service_id
                    print(f"Updated {instance_name}.providing.{svc_alias} -> ID {s.service_id}")
                # svc_data["major_version"] = s.major_version # Not in mock
                # svc_data["minor_version"] = s.minor_version

        # Update Required Services
        for svc_alias, svc_data in instance_data.get("required", {}).items():
             key_sv = svc_name_map.get(svc_alias)
             if key_sv and key_sv in service_map:
                s = service_map[key_sv]
                if hasattr(s, 'service_id'):
                    svc_data["service_id"] = s.service_id
                    print(f"Updated {instance_name}.required.{svc_alias} -> ID {s.service_id}")

    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)
    print("Configuration updated successfully.")

if __name__ == "__main__":
    generate_config()
