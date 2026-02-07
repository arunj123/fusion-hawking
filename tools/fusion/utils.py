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
            
            # Recursive update helper
            def update_node(node):
                if isinstance(node, dict):
                    for k, v in node.items():
                        if k == "ip" and isinstance(v, str):
                            node[k] = ip
                        elif k == "port" and isinstance(v, int):
                            node[k] = v + port_offset
                        else:
                            update_node(v)
                elif isinstance(node, list):
                    for item in node:
                        update_node(item)
            
            update_node(data)
            
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"Patched {rel_path} with IP: {ip} Offset: {port_offset}")
        except Exception as e:
            print(f"Failed to patch {rel_path}: {e}")
