import ipaddress
import collections
from typing import List, Dict, Tuple, Any

def validate_config(data: Dict[str, Any]) -> List[str]:
    """
    Validates the master configuration dictionary.
    Returns a list of error messages. Empty list implies valid config.
    """
    errors = []
    
    if "instances" not in data:
        errors.append("Missing top-level 'instances' key.")
        return errors

    instances = data["instances"]
    if not isinstance(instances, dict):
        errors.append("'instances' must be a dictionary.")
        return errors

    # Trackers for global conflict detection
    # (service_id, instance_id) -> list of instance_names providing it
    provided_services: Dict[Tuple[int, int], List[str]] = collections.defaultdict(list)
    
    # (ip, port, protocol) -> list of usage descriptions
    # Using string for IP to handle potential "localhost" resolution later if needed, 
    # but here we assume explicit IPs usually.
    used_ports: Dict[Tuple[str, int, str], List[str]] = collections.defaultdict(list)

    for inst_name, inst_cfg in instances.items():
        if "ip" not in inst_cfg:
            errors.append(f"Instance '{inst_name}' missing 'ip'.")
            continue
            
        ip = inst_cfg["ip"]
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            # Allow "localhost" ? Maybe strict for now.
            if ip != "localhost":
                errors.append(f"Instance '{inst_name}' has invalid IP: '{ip}'")

        # Validate SD
        if "sd" in inst_cfg:
            sd = inst_cfg["sd"]
            mc_ip = sd.get("multicast_ip")
            if mc_ip:
                try:
                    obj = ipaddress.ip_address(mc_ip)
                    if not obj.is_multicast:
                         errors.append(f"Instance '{inst_name}' SD multicast_ip '{mc_ip}' is not a multicast address.")
                except ValueError:
                    errors.append(f"Instance '{inst_name}' SD multicast_ip '{mc_ip}' is invalid.")
            
            mc_port = sd.get("multicast_port")
            if mc_port is not None:
                if not isinstance(mc_port, int) or mc_port <= 0 or mc_port > 65535:
                     errors.append(f"Instance '{inst_name}' SD multicast_port '{mc_port}' is invalid.")

        # Validate Providing Services
        if "providing" in inst_cfg:
            for svc_name, svc_cfg in inst_cfg["providing"].items():
                sid = svc_cfg.get("service_id")
                iid = svc_cfg.get("instance_id", 1) # Default to 1 if not typically specified, but usually strictly required?
                
                if sid is None:
                    errors.append(f"Instance '{inst_name}' service '{svc_name}' missing 'service_id'.")
                    continue
                
                # Check for duplicates
                provided_services[(sid, iid)].append(f"{inst_name}:{svc_name}")
                
                # Check Port
                port = svc_cfg.get("port")
                proto = svc_cfg.get("protocol", "udp")
                if port:
                    used_ports[(ip, port, proto)].append(f"{inst_name}:{svc_name}")

    # Analyze Global Conflicts
    for (sid, iid), providers in provided_services.items():
        if len(providers) > 1:
            errors.append(f"Duplicate Service (ID: {sid}, Instance: {iid}) provided by: {', '.join(providers)}")
            
    for (ip, port, proto), users in used_ports.items():
        if len(users) > 1:
             # If same instance uses same port for multiple services, that MIGHT be okay if runtime supports it (multiplexing),
             # but usually UDP unicast port is 1-to-1 or multiplexed. 
             # SOME/IP usually allows multiplexing services on same port.
             # But if DIFFERENT instances (apps) use same IP/Port, that's a crash.
             
             # Extract instance names
             msg_insts = set(u.split(':')[0] for u in users)
             if len(msg_insts) > 1:
                 errors.append(f"Port Conflict on {ip}:{port}/{proto}: Used by {', '.join(users)}")

    return errors

if __name__ == "__main__":
    import sys
    import json
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate Fusion Configuration")
    parser.add_argument("config_file", help="Path to config.json")
    args = parser.parse_args()
    
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
            print("Configuration is valid.")
            sys.exit(0)
    except Exception as e:
        print(f"Failed to load or validate config: {e}")
        sys.exit(1)
