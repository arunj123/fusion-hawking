import ipaddress
import collections
import re
from typing import List, Dict, Tuple, Any

# --- JSON Schema Definition ---
SCHEMA = {
    "type": "object",
    "required": ["instances", "interfaces"],
    "properties": {
        "interfaces": {
            "type": "object",
            "patternProperties": {
                "^.*$": {
                    "type": "object",
                    "required": ["name", "endpoints"],
                    "properties": {
                        "name": {"type": "string"},
                        "endpoints": {
                            "type": "object",
                            "patternProperties": {
                                "^.*$": {
                                    "type": "object",
                                    "required": ["ip", "port", "protocol"],
                                    "properties": {
                                        "ip": {"type": "string"},
                                        "port": {"type": "integer"},
                                        "protocol": {"type": "string", "enum": ["udp", "tcp"]},
                                        "version": {"type": "integer", "enum": [4, 6]}
                                    }
                                }
                            }
                        },
                        "sd": {
                            "type": "object",
                            "properties": {
                                "endpoint": {"type": "string"},
                                "endpoint_v4": {"type": "string"},
                                "endpoint_v6": {"type": "string"}
                            }
                        },
                        "server": {
                            "type": "object",
                            "properties": {
                                "endpoint": {"type": "string"},
                                "endpoint_v4": {"type": "string"},
                                "endpoint_v6": {"type": "string"}
                            }
                        }
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
                        "unicast_bind": {
                            "type": "object",
                            "patternProperties": {
                                "^.*$": {"type": "string"}
                            }
                        },
                        "providing": {
                            "type": "object",
                            "patternProperties": {
                                "^.*$": {
                                    "type": "object",
                                    "required": ["service_id", "offer_on"],
                                    "properties": {
                                        "service_id": {"type": "integer"},
                                        "instance_id": {"type": "integer"},
                                        "major_version": {"type": "integer"},
                                        "minor_version": {"type": "integer"},
                                        "offer_on": {
                                            "type": "object",
                                            "patternProperties": {
                                                 "^.*$": {"type": "string"}
                                            }
                                        },
                                        "eventgroups": {
                                            "type": "object",
                                            "patternProperties": {
                                                "^.*$": {
                                                    "type": "object",
                                                    "required": ["eventgroup_id", "events"],
                                                    "properties": {
                                                        "eventgroup_id": {"type": "integer"},
                                                        "events": {
                                                            "type": "array",
                                                            "items": {"type": "integer"}
                                                        },
                                                        "multicast": {
                                                            "type": "object",
                                                            "patternProperties": {
                                                                "^.*$": {"type": "string"}
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
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
                                        "find_on": {
                                            "type": "array",
                                            "items": {"type": "string"}
                                        },
                                        "protocol": {"type": "string", "enum": ["udp", "tcp"]},
                                        "preferred_interface": {"type": "string"} # Deprecated but allow for now? No, stick to design.
                                    },
                                    "additionalProperties": False
                                }
                            }
                        },
                        "sd": {
                            "type": "object",
                            "properties": {
                                "cycle_offer_ms": {"type": "integer"},
                                "request_response_delay_ms": {"type": "integer"},
                                "request_timeout_ms": {"type": "integer"},
                                "multicast_hops": {"type": "integer"}
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
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        
        # 1. Check for unexpected fields (Strictness)
        for key in data:
            is_defined = key in properties
            if not is_defined:
                # Check pattern properties
                for pattern in pattern_properties:
                    if re.match(pattern, key):
                        is_defined = True
                        break
            
            if not is_defined:
                errors.append(f"{path}: Unexpected field '{key}'")

        # 2. Recurse into properties
        for prop, sub_schema in properties.items():
            if prop in data:
                errors.extend(validate_json_structure(data[prop], sub_schema, f"{path}.{prop}" if path else prop))
        
        # 3. Recurse into pattern properties
        for pattern, sub_schema in pattern_properties.items():
            regex = re.compile(pattern)
            for key, value in data.items():
                # Skip if already validated by exact 'properties'
                if key in properties:
                    continue
                    
                if regex.match(key):
                    errors.extend(validate_json_structure(value, sub_schema, f"{path}.{key}" if path else key))

    return errors

def validate_config(data: Dict[str, Any]) -> List[str]:
    """
    Validates the master configuration dictionary.
    Returns a list of error messages. Empty list implies valid config.
    """
    # Level 0: Quick check - is this even a Fusion config?
    if not isinstance(data, dict):
        return ["Config must be a JSON object"]
        
    if "interfaces" not in data and "instances" not in data:
        return [] # Not a Fusion config, skip validation silently
        
    # Level 1: Schema Validation
    schema_errors = validate_json_structure(data, SCHEMA)
    if schema_errors:
        return ["Schema Validation Failed:"] + [f"  - {e}" for e in schema_errors]

    # Level 2: Semantic Validation
    errors = []
    
    interfaces = data.get("interfaces", {})
    instances = data.get("instances", {})

    # 1. Validate Interfaces block
    for iface_key, iface_cfg in interfaces.items():
        eps = iface_cfg.get("endpoints", {})
        
        # Validate SD endpoints
        sd_cfg = iface_cfg.get("sd", {})
        for key in ["endpoint", "endpoint_v4", "endpoint_v6"]:
            if key in sd_cfg:
                sd_ep_name = sd_cfg[key]
                if sd_ep_name not in eps:
                    errors.append(f"Interface '{iface_key}' SD {key} references unknown endpoint '{sd_ep_name}'")
                elif sd_ep_name:
                    sd_ep = eps[sd_ep_name]
                    if sd_ep.get("port", 0) == 0:
                        errors.append(f"Interface '{iface_key}' SD endpoint '{sd_ep_name}' must have a non-zero port.")
                    # Validate version match for endpoint_v4/v6
                    if key == "endpoint_v4" and sd_ep.get("version") != 4:
                        errors.append(f"Interface '{iface_key}' SD endpoint_v4 '{sd_ep_name}' must reference a version 4 endpoint (got version {sd_ep.get('version')})")
                    elif key == "endpoint_v6" and sd_ep.get("version") != 6:
                        errors.append(f"Interface '{iface_key}' SD endpoint_v6 '{sd_ep_name}' must reference a version 6 endpoint (got version {sd_ep.get('version')})")

        # Validate Server endpoints
        srv_cfg = iface_cfg.get("server", {})
        for key in ["endpoint", "endpoint_v4", "endpoint_v6"]:
            if key in srv_cfg:
                srv_ep_name = srv_cfg[key]
                if srv_ep_name not in eps:
                    errors.append(f"Interface '{iface_key}' server {key} references unknown endpoint '{srv_ep_name}'")

        # Validate IP addresses in endpoints
        for ep_name, ep_cfg in eps.items():
            try:
                ipaddress.ip_address(ep_cfg["ip"])
            except ValueError:
                errors.append(f"Interface '{iface_key}' endpoint '{ep_name}' has invalid IP: '{ep_cfg['ip']}'")

    # 2. Validate Instances block
    # (service_id, instance_id, major_version) -> list of providers
    provided_services: Dict[Tuple[int, int, int], List[str]] = collections.defaultdict(list)
    # (iface, ip, port, protocol) -> list of users
    used_ports: Dict[Tuple[str, str, int, str], List[str]] = collections.defaultdict(list)

    for inst_name, inst_cfg in instances.items():
        # Validate SD Unicast Bindings
        unicast_bind = inst_cfg.get("unicast_bind", {})
        for iface_key, ep_name in unicast_bind.items():
            if iface_key not in interfaces:
                errors.append(f"Instance '{inst_name}' unicast_bind references unknown interface '{iface_key}'")
                continue
            if ep_name not in interfaces[iface_key].get("endpoints", {}):
                errors.append(f"Instance '{inst_name}' unicast_bind references unknown endpoint '{ep_name}' on interface '{iface_key}'")
            else:
                 # Check port usage (Control Plane)
                ep = interfaces[iface_key]["endpoints"][ep_name]
                if ep["port"] != 0:
                    used_ports[(iface_key, ep["ip"], ep["port"], ep["protocol"].lower())].append(f"{inst_name}:SD")

        # Providing Services
        if "providing" in inst_cfg:
            for svc_name, svc_cfg in inst_cfg["providing"].items():
                sid = svc_cfg.get("service_id")
                iid = svc_cfg.get("instance_id", 1)
                major = svc_cfg.get("major_version", 0)
                offer_on = svc_cfg.get("offer_on", {})

                provided_services[(sid, iid, major)].append(f"{inst_name}:{svc_name}")

                for iface_key, ep_name in offer_on.items():
                    if iface_key not in interfaces:
                        errors.append(f"Instance '{inst_name}' service '{svc_name}' offer_on references unknown interface '{iface_key}'")
                        continue
                    
                    iface_eps = interfaces[iface_key].get("endpoints", {})
                    if ep_name not in iface_eps:
                        errors.append(f"Instance '{inst_name}' service '{svc_name}' offer_on references unknown endpoint '{ep_name}' on interface '{iface_key}'")
                        continue
                    
                    ep = iface_eps[ep_name]
                    if ep["port"] != 0:
                        used_ports[(iface_key, ep["ip"], ep["port"], ep["protocol"].lower())].append(f"{inst_name}:{svc_name}")

                # Validate Eventgroups
                evgs = svc_cfg.get("eventgroups", {})
                for evg_name, evg_cfg in evgs.items():
                    mcast_map = evg_cfg.get("multicast", {})
                    for if_key, m_ep_name in mcast_map.items():
                        if if_key not in interfaces:
                            errors.append(f"Eventgroup '{evg_name}' in '{inst_name}' references unknown interface '{if_key}'")
                            continue
                        if m_ep_name not in interfaces[if_key].get("endpoints", {}):
                            errors.append(f"Eventgroup '{evg_name}' in '{inst_name}' references unknown endpoint '{m_ep_name}' on interface '{if_key}'")

        # Required Services
        if "required" in inst_cfg:
            for req_name, req_cfg in inst_cfg["required"].items():
                find_on = req_cfg.get("find_on", [])
                for if_key in find_on:
                    if if_key not in interfaces:
                        errors.append(f"Instance '{inst_name}' required service '{req_name}' find_on references unknown interface '{if_key}'")

    # 3. Analyze Global Conflicts
    for (sid, iid, major), providers in provided_services.items():
        if len(providers) > 1:
            errors.append(f"Duplicate Service (ID: {sid}, Instance: {iid}, Major: {major}) provided by: {', '.join(providers)}")
            
    for (iface, ip, port, proto), users in used_ports.items():
        insts = set(u.split(':')[0] for u in users)
        if len(insts) > 1:
             # Allow sharing if all usages are for SD (e.g. SO_REUSEADDR on 0.0.0.0:30890)
            if all(u.endswith(":SD") for u in users):
                continue
            errors.append(f"Port Conflict on {iface}/{ip}:{port}/{proto}: Used by {', '.join(users)}")

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
