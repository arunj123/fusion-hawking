import socket
import os
import json
import ipaddress
import subprocess
import platform

def get_network_info():
    """
    Detect local network configuration including IPv4, IPv6, and Interface Name.
    Returns:
        dict: {
            'ipv4': str or None,
            'ipv6': str or None,
            'interface': str or None
        }
    """
    info = {'ipv4': None, 'ipv6': None, 'interface': None}

    # 1. Detect IPv4 via UDP connect (most reliable for finding source IP)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Connect to a non-routable address to find the primary interface
        s.connect(('10.255.255.255', 1))
        info['ipv4'] = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # 2. Detect IPv6 via UDP connect
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        # Google Public DNS IPv6 (any global address works)
        s.connect(('2001:4860:4860::8888', 80))
        info['ipv6'] = s.getsockname()[0]
        s.close()
    except Exception:
        # Fallback for local testing if no global IPv6
        try:
             # Try link-local detection if needed, but often not useful for config
             pass
        except:
             pass

    # 3. Detect Interface Name (Linux/WSL)
    if platform.system() == "Linux":
        try:
            # parsing `ip -4 route get <ip>`
            # Output: "<ip> via <gw> dev <dev> src <src_ip> ..."
            # OR:     "<ip> dev <dev> src <src_ip> ..."
            # Using 1.1.1.1 or 8.8.8.8 is safer than 10.255... which might not route if no default GW
            target_ip = "8.8.8.8"
            
            cmd = ["ip", "-4", "route", "get", target_ip]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                parts = result.stdout.split()
                if "dev" in parts:
                    idx = parts.index("dev")
                    if idx + 1 < len(parts):
                        info['interface'] = parts[idx + 1]
            
            # Fallback to loopback if no interface found or IP is loopback
            if not info['interface'] and (not info['ipv4'] or info['ipv4'].startswith('127.')):
                 info['interface'] = 'lo' 

        except Exception:
            pass
            
    return info

def get_local_ip_and_interface():
    """Legacy wrapper for backward compatibility."""
    info = get_network_info()
    # Fallback: if no IPv4, maybe return IPv6? Original code returned 127.0.0.1 default.
    ip = info['ipv4'] if info['ipv4'] else '127.0.0.1'
    return ip, info['interface']
    
def get_local_ip():
    return get_local_ip_and_interface()[0]
    
def get_ipv6():
    return get_network_info()['ipv6']

def patch_configs(ip_v4, root_dir, port_offset=0, ip_v6=None):
    """
    Update config files with detected local IPs and apply port offset.
    Arguments:
        ip_v4: Explicit IPv4 address (usually from get_local_ip, but can be passed in)
        root_dir: Project root
        port_offset: Port offset
        ip_v6: Explicit IPv6 address (optional, overrides detection)
    """
    config_paths = [
        "examples/integrated_apps/config.json",
        "examples/automotive_pubsub/config.json",
        "tests/tcp_test_config.json",
        "tests/test_config.json"
    ]
    
    # Resolve network info
    net_info = get_network_info()
    detected_ipv4 = net_info['ipv4']
    detect_ipv6 = net_info['ipv6']
    
    # Use passed IPv6 if provided, else use detected
    detected_ipv6 = ip_v6 if ip_v6 else detect_ipv6
    
    detected_iface = net_info['interface']
    
    # Use the passed IP if it matches detected, or if we are falling back to loopback
    # Use the passed IP if it matches detected, or if we are falling back to loopback
    target_iface = None
    if ip_v4 == '127.0.0.1':
        target_iface = 'lo'
    elif ip_v4 and ip_v4 == detected_ipv4:
        target_iface = detected_iface
    elif ip_v4 and not detected_ipv4:
         # If we forced an IP but detection failed (maybe loopback fallback), try to use detected interface if it looks like loopback
         if detected_iface == 'lo':
             target_iface = 'lo'

    for rel_path in config_paths:
        path = os.path.join(root_dir, rel_path)
        # print(f"DEBUG: Patching {path}, Exists: {os.path.exists(path)}")
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            
            modified = False

            # Helper to check if we should patch an IP
            def should_patch_ip(ip_str):
                try:
                    obj = ipaddress.ip_address(ip_str)
                    if obj.is_multicast: return False
                    # Allow patching loopback (we want to replace 127.0.0.1 with real IP for testing)
                    # if obj.is_loopback: return False 
                    return True
                except ValueError:
                    return False

            # 1. Patch Endpoints (Global)
            if "endpoints" in data:
                for ep_name, ep_cfg in data["endpoints"].items():
                    # Check version first
                    is_v6 = ep_cfg.get("version") == 6
                    
                    # IP Patching
                    if "ip" in ep_cfg:
                        current_ip = ep_cfg["ip"]
                        
                        # Decide whether to patch IPv4 or IPv6
                        if is_v6:
                            # If we have a detected IPv6, use it
                            if detected_ipv6 and should_patch_ip(current_ip):
                                ep_cfg["ip"] = detected_ipv6
                                modified = True
                            # If no global IPv6 but system supports it (has_ipv6), maybe fallback to loopback ::1?
                            elif socket.has_ipv6 and should_patch_ip(current_ip):
                                # Only patch if we are 100% sure we want to run locally
                                # For now, let's use ::1 if no global v6 is found, 
                                # implying we are in a contained env (like GitHub runner?)
                                # specific logic: if original is not localhost, make it localhost
                                ep_cfg["ip"] = "::1" 
                                modified = True
                        elif should_patch_ip(current_ip):
                            # Default IPv4
                            # Only patch if we have a valid IPv4
                            if ip_v4: 
                                ep_cfg["ip"] = ip_v4
                                modified = True
                        
                        # Interface Patching (only if we have a valid interface)
                        if "interface" in ep_cfg:
                             patched_ip = ep_cfg.get("ip")
                             # If we patched to localhost (v4 or v6), force interface to lo
                             if patched_ip == "127.0.0.1" or patched_ip == "::1":
                                 ep_cfg["interface"] = "lo"
                                 modified = True
                             elif target_iface:
                                 # Otherwise use the main interface detected
                                 ep_cfg["interface"] = target_iface
                                 modified = True
                        
                    # Port Offset
                    if "port" in ep_cfg and isinstance(ep_cfg["port"], int):
                        if port_offset != 0:
                            ep_cfg["port"] += port_offset
                            modified = True
            
            if modified:
                with open(path, 'w') as f:
                    json.dump(data, f, indent=4)
                
                msg = f"Patched {rel_path}: IPv4={ip_v4}"
                if detected_ipv6: msg += f", IPv6={detected_ipv6}"
                if target_iface: msg += f", Iface={target_iface}"
                if port_offset: msg += f", Offset={port_offset}"
                print(msg)
                
        except Exception as e:
            print(f"Failed to patch {rel_path}: {e}")
