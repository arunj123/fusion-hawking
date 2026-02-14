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
from .config_manager import ConfigGenerator

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

def patch_configs(ip_v4, root_dir, port_offset=0, ip_v6=None, config_paths=None):
    """
    Update config files using ConfigGenerator.
    Maintains legacy signature.
    """
    if config_paths is None:
        config_paths = [
            "examples/integrated_apps/config.json",
            "examples/automotive_pubsub/config.json",
            "examples/someipy_demo/client_config.json",
            "examples/versioning_demo/config.json",
            "tests/tcp_test_config.json",
            "tests/test_config.json"
        ]
    
    env = _get_env()
    gen = ConfigGenerator(env)
    
    # Determine Topology
    topology = "host"
    if ip_v4:
        if ip_v4.startswith("127."):
            topology = "loopback"
        elif ip_v4.startswith("10.0.") and env.has_vnet:
             # Heuristic: if IP looks like VNet IP and VNet is available, assume VNet topology
             topology = "vnet"
    
    # TODO: Pass ip_v6 and overrides to ConfigGenerator if necessary?
    # ConfigGenerator logic currently patches based on topology rules, ignoring explicit ip_v4 arg 
    # unless we extend ConfigGenerator to accept override IPs.
    # The legacy patch_configs accepted 'ip_v4' and patched it everywhere.
    # My ConfigGenerator logic currently tries to be smart/safe.
    # To support legacy behavior where `ip_v4` is forced (e.g. 127.0.0.1 forced),
    # ConfigGenerator's "loopback" topology handles the 127.0.0.1 case.
    # But if ip_v4 is some specific host IP? ConfigGenerator "host" topology detects primary IP.
    # If the user passed a SPECIFIC IP different from primary, ConfigGenerator ignores it?
    # This might be a regression.
    # However, usually `ip_v4` passed here comes from `get_local_ip()`, which IS the primary IP.
    # So "host" topology using `env.primary_ip` should yield the same result.
    
    # Exception: reproduce_patch_bug.py passes specific dummy IPs.
    # If I run that script, ConfigGenerator "vnet" topology will handle 10.0.x.x IPs correctly 
    # (by NOT patching them to host interfaces).
    
    for rel_path in config_paths:
        path = os.path.join(root_dir, rel_path)
        if not os.path.exists(path):
            continue
            
        try:
            # Overwrite the file using ConfigGenerator
            gen.generate(path, path, topology=topology, port_offset=port_offset, override_ipv4=ip_v4)
            print(f"Patched {rel_path} using topology '{topology}' (Offset: {port_offset}, Override: {ip_v4})")
        except Exception as e:
            print(f"Failed to patch {rel_path}: {e}")
            logger.error(f"Failed to patch {rel_path}: {e}")

# Expose new modules for direct usage if needed
def get_environment():
    return _get_env()
