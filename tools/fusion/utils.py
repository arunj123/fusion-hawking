import socket
import os
import json
import ipaddress
import subprocess
import platform
import re
import struct
import sys
import logging

from .environment import NetworkEnvironment


logger = logging.getLogger("fusion.utils")

# Global Environment Cache
_ENV = None

def _get_env():
    global _ENV
    if _ENV is None:
        _ENV = NetworkEnvironment()
        _ENV.detect()
    return _ENV


# ─────────────────────────────────────────────────────────────
#  Shared Utilities (consolidated from test files)
# ─────────────────────────────────────────────────────────────

def to_wsl(path):
    """Convert a Windows path to a WSL-accessible path."""
    if not path:
        return path
    return path.replace("\\", "/").replace("C:", "/mnt/c").replace("c:", "/mnt/c")


def find_binary(name, search_dirs=None, root=None):
    """
    Find a compiled binary by name across common build output directories.
    
    Args:
        name: Binary name WITHOUT extension (e.g. 'client_fusion', 'someipy_client')
        search_dirs: Optional list of directories to search in addition to defaults
        root: Project root directory (defaults to PROJECT_ROOT detection)
        
    Returns:
        str or None: Full path to the binary, or None if not found
    """
    if root is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    target = f"{name}.exe" if os.name == 'nt' else name
    
    # Default search locations
    candidates = [
        os.path.join(root, "build", "Release", target),
        os.path.join(root, "build", target),
        os.path.join(root, "build_linux", target),
        os.path.join(root, "build_linux", "examples", "someipy_demo", target),
        os.path.join(root, "examples", "someipy_demo", "build", "Release", target),
        os.path.join(root, "examples", "someipy_demo", "build", target),
        os.path.join(root, "target", "debug", target),
        os.path.join(root, "target", "release", target),
    ]
    
    # Add custom search dirs
    if search_dirs:
        for d in search_dirs:
            candidates.append(os.path.join(d, target))
    
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def get_ns_iface(env, ns, ip):
    """
    Get the interface name for a given IP inside a network namespace.
    
    Args:
        env: NetworkEnvironment instance
        ns: Namespace name (e.g. 'ns_ecu1')
        ip: IP address to look up
        
    Returns:
        str: Interface name (e.g. 'veth0'), or 'veth0' as fallback
    """
    # Try rich topology first
    result = env.get_vnet_iface_for_ip(ns, ip)
    if result:
        return result
    
    # Try legacy map
    ns_map = env.vnet_interface_map.get(ns, {})
    return ns_map.get(ip, 'veth0')


# ─────────────────────────────────────────────────────────────
#  Legacy API — wrappers around NetworkEnvironment
# ─────────────────────────────────────────────────────────────

def detect_environment():
    """
    Detect environment capabilities for test selection and config patching.
    Wrapper around NetworkEnvironment for backward compatibility.
    """
    env = _get_env()
    
    caps = {
        'os': env.os_type,
        'is_wsl': env.is_wsl,
        'is_ci': bool(os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS')),
        'has_multicast': env.supports_multicast,
        'has_ipv4': env.has_ipv4,
        'has_ipv6': env.has_ipv6,
        'has_netns': env.has_vnet,
        'has_veth': env.has_vnet,
        'interfaces': list(env.interfaces.keys()),
        'primary_ipv4': env.primary_ip,
        'primary_ipv6': None,
        'loopback_interface': 'lo' if env.os_type != 'Windows' else get_loopback_interface_name(),
    }
    
    # Attempt to populate primary_ipv6 from interface data
    if env.primary_interface and env.primary_interface in env.interfaces:
        v6_list = env.interfaces[env.primary_interface].get('ip_v6', [])
        if v6_list: caps['primary_ipv6'] = v6_list[0]

    logger.info(f"Environment capabilities: {json.dumps(caps, indent=2)}")
    return caps


def get_loopback_interface_name():
    """Detect the loopback interface name for the current OS."""
    if os.name != 'nt':
        return 'lo'
    
    try:
        cmd = ["netsh", "interface", "ipv4", "show", "interfaces"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        lines = result.stdout.splitlines()
        for line in lines:
            if "Loopback" in line:
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) >= 5:
                    return parts[4]
    except Exception:
        pass
    
    return 'Loopback Pseudo-Interface 1'

def get_network_info():
    """
    Detect local network configuration including IPv4, IPv6, and Interface Name.
    Wrapper around NetworkEnvironment.
    """
    env = _get_env()
    info = {'ipv4': env.primary_ip, 'ipv6': None, 'interface': env.primary_interface, 'interface_index': 0}
    
    if env.primary_interface and env.primary_interface in env.interfaces:
        v6s = env.interfaces[env.primary_interface].get('ip_v6', [])
        if v6s: info['ipv6'] = v6s[0]

    if not info['ipv4']:
        info['ipv4'] = '127.0.0.1'
        info['interface'] = get_loopback_interface_name()

    return info

def get_local_ip_and_interface():
    info = get_network_info()
    return info['ipv4'], info['interface']
    
def get_local_ip():
    return get_local_ip_and_interface()[0]
    
def get_ipv6():
    return get_network_info()['ipv6']


# ─────────────────────────────────────────────────────────────
#  Config Patching
# ─────────────────────────────────────────────────────────────

def patch_test_config(config_path, env):
    """
    Patches a config file to use the correct IPs and interfaces for the current environment.
    Especially useful for VNet (namespace) testing where host IPs must be replaced
    with bindable IPs or the primary IP.
    """
    if not os.path.exists(config_path):
        return
        
    with open(config_path, 'r') as f:
        config = json.load(f)
        
    updated = False
    
    primary_ip = env.primary_ip or "127.0.0.1"
    
    if "interfaces" in config:
        for iface_name, iface_data in config["interfaces"].items():
            # Update physical interface name if it's 'primary'
            if iface_name == "primary":
                target_iface = env.primary_interface
                if env.has_vnet:
                    for ns_map in env.vnet_interface_map.values():
                        if ns_map:
                            target_iface = next(iter(ns_map.values()))
                            break
                
                if target_iface and iface_data.get("name") != target_iface:
                    iface_data["name"] = target_iface
                    updated = True
            
            if "endpoints" in iface_data:
                for ep_name, ep_data in iface_data["endpoints"].items():
                    curr_ip = ep_data.get("ip")
                    if curr_ip in ["127.0.0.1", "0.0.0.0", "localhost"]:
                        if ep_data.get("ip") != primary_ip:
                            ep_data["ip"] = primary_ip
                            updated = True
                    
                    # Set version if missing
                    if "version" not in ep_data:
                        ep_data["version"] = 6 if ":" in ep_data.get("ip", "") else 4
                        updated = True

    if updated:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
        logger.info(f"Patched config at {config_path} (VNet={env.has_vnet}, IP={primary_ip})")
