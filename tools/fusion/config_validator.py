import ipaddress
import collections
from typing import List, Dict, Tuple, Any

# --- JSON Schema Definition ---
SCHEMA = {
    "type": "object",
    "required": ["instances"],
    "properties": {
        "endpoints": {
            "type": "object",
            "patternProperties": {
                "^.*$": {
                    "type": "object",
                    "required": ["ip", "interface", "port", "protocol"],
                    "properties": {
                        "ip": {"type": "string"},
                        "interface": {"type": "string"},
                        "version": {"type": "integer", "enum": [4, 6]},
                        "port": {"type": "integer"},
                        "protocol": {"type": "string", "enum": ["udp", "tcp"]}
                    }
                }
            }
        },
        "instances": {
            "type": "object",
            "patternProperties": {
                "^.*$": {
                    "type": "object",
                    "properties": {
                        "ip": {"type": "string"},
                        "ip_v6": {"type": "string"},
                        "ip_version": {"type": "integer"},
                        "providing": {
                            "type": "object",
                            "patternProperties": {
                                "^.*$": {
                                    "type": "object",
                                    "required": ["service_id", "endpoint"],
                                    "properties": {
                                        "service_id": {"type": "integer"},
                                        "instance_id": {"type": "integer"},
                                        "major_version": {"type": "integer"},
                                        "minor_version": {"type": "integer"},
                                        "endpoint": {"type": "string"}
                                    },
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": {
                            "type": "object",
                            "patternProperties": {
                                "^.*$": {
                                    "type": "object",
                                    "required": ["service_id"],
                                    "properties": {
                                        "service_id": {"type": "integer"},
                                        "instance_id": {"type": "integer"},
                                        "major_version": {"type": "integer"},
                                        "minor_version": {"type": "integer"},
                                        "endpoint": {"type": "string"}
                                    },
                                    "additionalProperties": False
                                }
                            }
                        },
                        "sd": {
                            "type": "object",
                            "properties": {
                                "multicast_ip": {"type": "string"},
                                "multicast_port": {"type": "integer"},
                                "multicast_endpoint": {"type": "string"},
                                "multicast_endpoint_v6": {"type": "string"},
                                "cycle_offer_ms": {"type": "integer"},
                                "request_response_delay_ms": {"type": "integer"},
                                "request_timeout_ms": {"type": "integer"}
                            }
                        }
                    }
                }
            }
        }
    }
}

def validate_json_structure(data: Any, schema: Dict[str, Any], path: str = "") -> List[str]:
    """
    Recursively validates data against a simple JSON schema.
    """
    errors = []
    
    # Type check
    expected_type = schema.get("type")
    if expected_type:
        if expected_type == "object" and not isinstance(data, dict):
            return [f"{path}: Expected object, got {type(data).__name__}"]
        elif expected_type == "string" and not isinstance(data, str):
            return [f"{path}: Expected string, got {type(data).__name__}"]
        elif expected_type == "integer" and not isinstance(data, int):
            return [f"{path}: Expected integer, got {type(data).__name__}"]
        elif expected_type == "boolean" and not isinstance(data, bool):
            return [f"{path}: Expected boolean, got {type(data).__name__}"]
    
    # Required fields
    if "required" in schema and isinstance(data, dict):
        for req in schema["required"]:
            if req not in data:
                errors.append(f"{path}: Missing required field '{req}'")
    
    if errors: return errors

    # Enum check
    if "enum" in schema and data not in schema["enum"]:
        return [f"{path}: Value '{data}' is not in enum {schema['enum']}"]

    # Properties check (for objects)
    if expected_type == "object" and isinstance(data, dict):
        # Check defined properties
        if "properties" in schema:
            for prop, sub_schema in schema["properties"].items():
                if prop in data:
                    errors.extend(validate_json_structure(data[prop], sub_schema, f"{path}.{prop}" if path else prop))
        
        # Check pattern properties
        if "patternProperties" in schema:
            import re
            for pattern, sub_schema in schema["patternProperties"].items():
                regex = re.compile(pattern)
                for key, value in data.items():
                    # Skip if already validated by exact 'properties' (optional, but good for overlap)
                    if "properties" in schema and key in schema["properties"]:
                        continue
                        
                    if regex.match(key):
                        errors.extend(validate_json_structure(value, sub_schema, f"{path}.{key}" if path else key))

    return errors

def validate_config(data: Dict[str, Any]) -> List[str]:
    """
    Validates the master configuration dictionary.
    Returns a list of error messages. Empty list implies valid config.
    """
    # Level 1: Schema Validation
    schema_errors = validate_json_structure(data, SCHEMA)
    if schema_errors:
        return ["Schema Validation Failed:"] + [f"  - {e}" for e in schema_errors]

    # Level 2: Semantic Validation
    errors = []
    
    endpoints = data.get("endpoints", {})
    instances = data.get("instances", {})

    # Validate Endpoints Logic
    for ep_name, ep_cfg in endpoints.items():
        if "ip" in ep_cfg:
            try:
                ipaddress.ip_address(ep_cfg["ip"])
            except ValueError:
                errors.append(f"Endpoint '{ep_name}' has invalid IP: '{ep_cfg['ip']}'")

    # Trackers for global conflict detection
    # (service_id, instance_id, major_version) -> list of instance_names providing it
    provided_services: Dict[Tuple[int, int, int], List[str]] = collections.defaultdict(list)
    
    # (ip, port, protocol) -> list of usage descriptions (instance:service)
    used_ports: Dict[Tuple[str, int, str], List[str]] = collections.defaultdict(list)

    for inst_name, inst_cfg in instances.items():
        # Instance IP (Legacy or Fallback)
        inst_ip = inst_cfg.get("ip", "127.0.0.1")
        
        # Validate Providing Services
        if "providing" in inst_cfg:
            for svc_name, svc_cfg in inst_cfg["providing"].items():
                sid = svc_cfg.get("service_id")
                iid = svc_cfg.get("instance_id", 1) 
                major = svc_cfg.get("major_version", 0)
                
                # Check for duplicates
                provided_services[(sid, iid, major)].append(f"{inst_name}:{svc_name}")
                
                # Resolve Endpoint
                resolved_ip = inst_ip
                resolved_port = svc_cfg.get("port", 0)
                resolved_proto = svc_cfg.get("protocol", "udp").lower()
                
                ep_name = svc_cfg.get("endpoint")
                if ep_name:
                    if ep_name not in endpoints:
                        errors.append(f"Instance '{inst_name}' service '{svc_name}' references unknown endpoint '{ep_name}'.")
                    else:
                        ep = endpoints[ep_name]
                        resolved_ip = ep.get("ip", resolved_ip)
                        if "port" in ep and ep["port"] != 0:
                            resolved_port = ep["port"]
                        if "protocol" in ep:
                            resolved_proto = ep["protocol"].lower()

                # Override if service specifically sets port/protocol even with endpoint?
                # Usually service config overrides endpoint config.
                if svc_cfg.get("port"): resolved_port = svc_cfg["port"]
                if svc_cfg.get("protocol"): resolved_proto = svc_cfg["protocol"].lower()

                if resolved_port != 0:
                    used_ports[(resolved_ip, resolved_port, resolved_proto)].append(f"{inst_name}:{svc_name}")

    # Analyze Global Conflicts
    for (sid, iid, major), providers in provided_services.items():
        if len(providers) > 1:
            if not f"Duplicate Service (ID: {sid}, Instance: {iid}, Major: {major})" in errors: # Avoid spam
                 errors.append(f"Duplicate Service (ID: {sid}, Instance: {iid}, Major: {major}) provided by: {', '.join(providers)}")
            
    for (ip, port, proto), users in used_ports.items():
        # Check if users are from different instances
        insts = set(u.split(':')[0] for u in users)
        if len(insts) > 1:
            errors.append(f"Port Conflict on {ip}:{port}/{proto}: Used by {', '.join(users)}")

    return errors

if __name__ == "__main__":
    import sys
    import json
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description="Validate Fusion Configuration")
    parser.add_argument("config_file", help="Path to config.json")
    args = parser.parse_args()
    
    if not os.path.exists(args.config_file):
        print(f"Error: Config file not found: {args.config_file}")
        sys.exit(1)

    try:
        with open(args.config_file, "r") as f:
            data = json.load(f)
        
        errs = validate_config(data)
        if errs:
            print("Configuration Errors Found:")
            for e in errs:
                print(f" - {e}")
            sys.exit(1)
        else:
            print(f"Configuration '{args.config_file}' is valid.")
            sys.exit(0)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON format in {args.config_file}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Failed to load or validate config: {e}")
        sys.exit(1)
