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

def detect_environment():
    """
    Detect environment capabilities for test selection and config patching.
    Wrapper around NetworkEnvironment for backward compatibility.
    """
    env = _get_env()
    
    # Map NetworkEnvironment fields to legacy dict structure
    caps = {
        'os': env.os_type,
        'is_wsl': env.is_wsl,
        'is_ci': bool(os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS')),
        'has_multicast': env.supports_multicast,
        'has_ipv6': env.has_ipv6,
        'has_netns': env.has_vnet, # Simplify: if we detected VNet utils, we assume netns support
        'has_veth': env.os_type == 'Linux', # Assumption for now
        'interfaces': list(env.interfaces.keys()),
        'primary_ipv4': env.primary_ip,
        'primary_ipv6': None, # TODO: Extract if needed
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
    
    # Windows dynamic detection (Legacy logic preserved for safety if Env fails)
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
    
    # Try to find IPv6 on primary interface
    if env.primary_interface and env.primary_interface in env.interfaces:
        v6s = env.interfaces[env.primary_interface].get('ip_v6', [])
        if v6s: info['ipv6'] = v6s[0]

    # Legacy: if no primary IP detected, fallback to loopback?
    if not info['ipv4']:
        info['ipv4'] = '127.0.0.1'
        info['interface'] = get_loopback_interface_name()

    return info

def get_local_ip_and_interface():
    """Legacy wrapper for backward compatibility."""
    info = get_network_info()
    return info['ipv4'], info['interface']
    
def get_local_ip():
    return get_local_ip_and_interface()[0]
    
def get_ipv6():
    return get_network_info()['ipv6']


