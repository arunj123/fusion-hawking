import socket
import os
import json
import ipaddress
import subprocess
import platform
import re

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
    info = {'ipv4': None, 'ipv6': None, 'interface': None, 'interface_index': 0}

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
        # Fallback: check if loopback is available for local testing
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s.connect(('::1', 1))
            info['ipv6'] = s.getsockname()[0]
            s.close()
        except:
             pass

    # 3. Detect Interface Name
    if platform.system() == "Linux":
        try:
            # parsing `ip -4 route get <ip>`
            target_ip = "8.8.8.8"
            cmd = ["ip", "-4", "route", "get", target_ip]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                parts = result.stdout.split()
                if "dev" in parts:
                    idx = parts.index("dev")
                    if idx + 1 < len(parts):
                        info['interface'] = parts[idx + 1]
            if not info['interface'] and (not info['ipv4'] or info['ipv4'].startswith('127.')):
                 info['interface'] = 'lo' 
        except Exception: pass
    elif platform.system() == "Windows":
        try:
            # On Windows, we can use netsh to find the interface name for a given IP
            if info['ipv4']:
                cmd = ["netsh", "interface", "ipv4", "show", "address"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                # Look for the interface that has our IP
                # Format:
                # Configuration for interface "Ethernet"
                # ...
                # IP Address: 192.168.0.113
                lines = result.stdout.splitlines()
                current_iface = None
                for line in lines:
                    if 'interface "' in line:
                        current_iface = line.split('"')[1]
                    if info['ipv4'] in line:
                        info['interface'] = current_iface
                        break
            elif info['ipv6']:
                # Similar for IPv6
                cmd = ["netsh", "interface", "ipv6", "show", "address"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                lines = result.stdout.splitlines()
                current_iface = None
                for line in lines:
                    if 'interface "' in line:
                        current_iface = line.split('"')[1]
                    if info['ipv6'].lower() in line.lower():
                        info['interface'] = current_iface
                        break
            
            if not info['interface']:
                info['interface'] = 'Loopback Pseudo-Interface 1' # Windows typical name

            # NEW: Detect numerical index (Idx) using netsh interface show interface
            if info['interface']:
                cmd = ["netsh", "interface", "ipv4", "show", "interfaces"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                # Format:
                # Idx     Met         MTU          State          Name
                # ---  ----------  ----------  ------------  ---------------------------
                #   1          75  4294967295  connected     Loopback Pseudo-Interface 1
                lines = result.stdout.splitlines()
                for line in lines:
                    if info['interface'] in line:
                         match = re.match(r"^\s*(\d+)", line)
                         if match:
                             info['interface_index'] = int(match.group(1))
                             break
        except Exception: pass
            
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

def patch_configs(ip_v4, root_dir, port_offset=0, ip_v6=None, config_paths=None):
    """
    Update config files with detected local IPs and apply port offset.
    Arguments:
        ip_v4: Explicit IPv4 address (usually from get_local_ip, but can be passed in)
        root_dir: Project root
        port_offset: Port offset
        ip_v6: Explicit IPv6 address (optional, overrides detection)
        config_paths: Custom list of config files to patch
    """
    if config_paths is None:
        config_paths = [
            "examples/integrated_apps/config.json",
            "examples/integrated_apps/cpp_app/config.json",
            "examples/automotive_pubsub/config.json",
            "examples/someipy_demo/client_config.json",
            "tests/tcp_test_config.json",
            "tests/test_config.json"
        ]
    
    # Resolve network info
    net_info = get_network_info()
    
    # If IPv4 is forced to loopback, force IPv6 too for consistency
    if ip_v4 == "127.0.0.1" and not ip_v6:
        ip_v6 = "::1"

    if ip_v6: net_info['ipv6'] = ip_v6
    
    # If IPv6 is missing, attempt to configure it on Linux
    if not net_info['ipv6'] and platform.system() == "Linux":
        if os.geteuid() == 0:
            try:
                iface = net_info.get('interface', 'eth0')
                subprocess.run(["ip", "addr", "add", "2001:db8::1/64", "dev", iface], check=True)
                net_info['ipv6'] = "2001:db8::1"
            except Exception: pass
    
    if not net_info['ipv4']:
        print("CRITICAL: No IPv4 address detected. Please check network configuration.")
        # We don't exit here to allow multi-stack attempts, but runtimes will fail.

    # Use passed IPv6 if provided, else use detected
    detected_ipv6 = net_info['ipv6']
    
    detected_iface = net_info['interface']
    
    # Use the passed IP if it matches detected, or if we are falling back to loopback
    # Use the passed IP if it matches detected, or if we are falling back to loopback
    target_iface = None
    if ip_v4 == '127.0.0.1':
        target_iface = 'lo'
    elif ip_v4 and ip_v4 == net_info['ipv4']:
        target_iface = detected_iface
    elif ip_v4 and not net_info['ipv4']:
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
                        
                        # Decide whether to patch IPv4, IPv6, or Multicast
                        if is_v6:
                            # If we have a detected IPv6, use it
                            if detected_ipv6 and should_patch_ip(current_ip):
                                ep_cfg["ip"] = detected_ipv6
                                modified = True
                            # Fallback to local loopback if has_ipv6() (even if no global addr)
                            elif socket.has_ipv6 and should_patch_ip(current_ip):
                                ep_cfg["ip"] = "::1" 
                                modified = True
                        else:
                            # IPv4 or Multicast
                            try:
                                obj = ipaddress.ip_address(current_ip)
                                if obj.is_multicast:
                                    # Multicast Isolation: shift last octet based on port_offset (assuming offset in 100s)
                                    if port_offset != 0:
                                        octets = list(obj.packed)
                                        # Simple shift: add offset // 100 to last octet
                                        octets[3] = (octets[3] + (port_offset // 100)) % 256
                                        ep_cfg["ip"] = str(ipaddress.ip_address(bytes(octets)))
                                        modified = True
                                elif should_patch_ip(current_ip):
                                    # Regular IPv4
                                    if ip_v4:
                                        # Windows loopback partitioning
                                        if os.name == 'nt' and ip_v4 == '127.0.0.1':
                                            if "python" in ep_name.lower():
                                                ep_cfg["ip"] = "127.0.0.2"
                                            elif "cpp" in ep_name.lower():
                                                ep_cfg["ip"] = "127.0.0.3"
                                            elif "rust" in ep_name.lower():
                                                ep_cfg["ip"] = "127.0.0.4"
                                            else:
                                                ep_cfg["ip"] = "127.0.0.1"
                                        else:
                                            ep_cfg["ip"] = ip_v4
                                        modified = True
                            except ValueError:
                                pass
                        
                        # Interface Patching (Mandatory)
                        final_ip = ep_cfg.get("ip")
                        
                        # Use force_lo if final_ip is a loopback address
                        is_loopback = final_ip and (final_ip.startswith("127.") or final_ip == "::1" or final_ip == "localhost")
                        
                        # Update interface name
                        # Rules:
                        # 1. If it's a loopback IP, it MUST use 'lo' (Linux) or Windows loopback
                        # 2. Otherwise, if target_iface is forced (e.g. from get_local_ip), use it
                        # 3. Else fallback to detected interface
                        
                        if is_loopback:
                            new_iface = "lo" if os.name != 'nt' else "Loopback Pseudo-Interface 1"
                            if ep_cfg.get('interface') != new_iface:
                                ep_cfg['interface'] = new_iface
                                modified = True
                        elif target_iface:
                            if ep_cfg.get('interface') != target_iface:
                                ep_cfg['interface'] = target_iface
                                modified = True
                        elif net_info['interface'] and net_info['interface'] != 'lo':
                            if ep_cfg.get('interface') != net_info['interface']:
                                ep_cfg['interface'] = net_info['interface']
                                modified = True
                        
                        # Explicitly remove interface_index as runtimes now resolve dynamically
                        if ep_cfg.pop('interface_index', None) is not None:
                            modified = True
                        
                        # Ensure we ALWAYS have an interface field if it's missing or set to a generic placeholder (like eth0)
                        if not ep_cfg.get("interface") or ep_cfg.get("interface") == "eth0":
                            if is_loopback:
                                ep_cfg["interface"] = "lo" if os.name != 'nt' else "Loopback Pseudo-Interface 1"
                                modified = True
                            elif net_info['interface']:
                                ep_cfg["interface"] = net_info["interface"]
                                modified = True
                            else:
                                ep_cfg["interface"] = "lo" if os.name != 'nt' else "Loopback Pseudo-Interface 1"
                                modified = True
                        
                    # Port Offset
                    if "port" in ep_cfg and isinstance(ep_cfg["port"], int):
                        # Don't apply offset to ephemeral ports (0)
                        if port_offset != 0 and ep_cfg["port"] != 0:
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
