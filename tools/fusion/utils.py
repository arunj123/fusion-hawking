import socket
import os
import json

def get_local_ip():
    """Detect the first non-loopback working interface's IP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a non-routable address to find the primary interface
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        # Fallback to loopback if no external interface is found/active
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def patch_configs(ip, root_dir, port_offset=0):
    """Update config files with the detected local IP and apply port offset."""
    config_paths = [
        "examples/integrated_apps/config.json",
        "examples/automotive_pubsub/config.json"
    ]
    for rel_path in config_paths:
        path = os.path.join(root_dir, rel_path)
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            
            # Specific Instance Patching for SD
            if "instances" in data:
                for inst_name, inst_cfg in data["instances"].items():
                    # 1. Patch Unicast IP
                    inst_cfg["ip"] = ip
                    
                    # 2. Patch SD Config
                    if "sd" not in inst_cfg:
                        inst_cfg["sd"] = {}
                    
                    # Ensure defaults + offset
                    base_sd_port = inst_cfg["sd"].get("multicast_port", 30490)
                    inst_cfg["sd"]["multicast_port"] = base_sd_port + port_offset
                    
                    if "multicast_ip" not in inst_cfg["sd"]:
                        inst_cfg["sd"]["multicast_ip"] = "224.0.0.1"

            # Recursive update for other ports (services)
            update_node(data)
            
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"Patched {rel_path} with IP: {ip} Offset: {port_offset}")
        except Exception as e:
            print(f"Failed to patch {rel_path}: {e}")
