import platform
import subprocess
import json
import shutil
import ipaddress
import socket
import os
import sys
import re

class NetworkEnvironment:
    """
    Detects the host environment's network capabilities and virtual network topology.
    
    This is the single source of truth for all environment-dependent decisions
    in config generation and test selection. Runtime code never performs environment
    detection — only this class does, and it feeds into config generation.
    
    Attributes:
        os_type:            'Windows' | 'Linux' | 'Darwin'
        is_wsl:             True if running under WSL
        has_ipv4:           True if IPv4 sockets are available
        has_ipv6:           True if IPv6 sockets are available
        supports_multicast: True if multicast is available on at least one interface
        has_vnet:           True if the VNet topology (br0, namespaces) is detected
        vnet_has_ipv6:      True if VNet namespaces have IPv6 addresses
        vnet_has_multicast: True if VNet interfaces have multicast capability
        vnet_topology:      Rich per-namespace interface info (see _inspect_namespace)
    """
    def __init__(self):
        self.os_type = platform.system() # Windows, Linux, Darwin
        self.is_wsl = False
        self.distro = None
        self.is_android = False
        self.is_qnx = False
        
        # Privileges
        self.is_root = (os.name != 'nt' and os.geteuid() == 0)
        self.can_sudo = False 
        
        # Network
        self.interfaces = {} # name -> {ip_v4: [], ip_v6: [], type: 'loopback'|'ethernet'|'bridge'|'veth', flags: []}
        self.primary_interface = None
        self.primary_ip = None
        
        # VNet
        self.has_vnet = False
        self.vnet_namespaces = [] # List of ns names
        self.vnet_interface_map = {} # ns_name -> {ip -> iface_name} (legacy, kept for compat)
        self.vnet_topology = {}     # ns_name -> { iface_name: { "ipv4": str|None, "ipv6": str|None, "flags": [] } }
        
        # Capabilities (explicit flags — never assume)
        self.has_ipv4 = False
        self.has_ipv6 = False
        self.supports_multicast = False
        self.supports_broadcast = False
        self.loopback_multicast_ok = True
        self.vnet_has_ipv6 = False
        self.vnet_has_multicast = False
        
    def detect(self):
        """Detect current network environment capabilities."""
        # 0. Forced No-VNet Override
        if os.environ.get("FUSION_NO_VNET") == "1":
            self.platform = sys.platform
            self.is_wsl = "microsoft" in platform.release().lower()
            self.has_vnet = False # Forced False
            self.has_netns = False
            self.has_veth = False
            self.interfaces = {} # Minimal/empty or re-scan properly without vnet assumptions
            # Still detect basic interfaces for physical run
            self._detect_network_interfaces() # Corrected from _detect_interfaces()
            return

        # 1. Platform & WSL
        self.platform = sys.platform
        self._detect_os() # Kept original _detect_os() call as it sets os_type and distro
        self._detect_privileges()
        self._detect_network_interfaces()
        self._detect_capabilities()
        # Try to set up VNet if on Linux and we have sudo
        if self.os_type == 'Linux' and not self.has_vnet:
            self._try_setup_vnet()
        self._detect_vnet()

    def _detect_os(self):
        if self.os_type == 'Linux':
            try:
                with open('/proc/version', 'r') as f:
                    content = f.read().lower()
                    if 'microsoft' in content:
                        self.is_wsl = True
                        self.distro = "WSL"
            except Exception: pass
        elif self.os_type == 'Windows':
            pass

    def _detect_privileges(self):
        if self.os_type != 'Windows':
            if self.is_root:
                self.can_sudo = True
            else:
                # Check passwordless sudo
                try:
                    r = subprocess.run(['sudo', '-n', 'true'], capture_output=True)
                    self.can_sudo = (r.returncode == 0)
                except Exception:
                    self.can_sudo = False

    def _detect_network_interfaces(self):
        # Universal approach: use socket to find primary, subprocess for details
        try:
            # Find primary interface via routing
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            self.primary_ip = s.getsockname()[0]
            s.close()
        except Exception:
            self.primary_ip = '127.0.0.1'

        if self.os_type == 'Linux':
            self._detect_linux_interfaces()
        elif self.os_type == 'Windows':
            self._detect_windows_interfaces()

    def _detect_linux_interfaces(self):
        try:
            # Parse ip -j addr
            r = subprocess.run(['ip', '-j', 'addr'], capture_output=True, text=True)
            try:
                data = json.loads(r.stdout)
                for iface in data:
                    name = iface['ifname']
                    ips_v4 = [addr['local'] for addr in iface.get('addr_info', []) if addr['family'] == 'inet']
                    ips_v6 = [addr['local'] for addr in iface.get('addr_info', []) if addr['family'] == 'inet6']
                    
                    iface_type = 'ethernet'
                    if name == 'lo': iface_type = 'loopback'
                    elif 'link_type' in iface and iface['link_type'] == 'ether':
                         # Check for bridge or veth
                         if 'linkinfo' in iface: # sometimes available in detailed output
                             kind = iface.get('linkinfo', {}).get('info_kind')
                             if kind: iface_type = kind
                    
                    # Heuristic for type if not explicit
                    if name.startswith('br'): iface_type = 'bridge'
                    elif name.startswith('veth'): iface_type = 'veth'
                    elif name.startswith('docker'): iface_type = 'bridge'

                    self.interfaces[name] = {
                        'ip_v4': ips_v4,
                        'ip_v6': ips_v6,
                        'type': iface_type,
                        'flags': iface.get('flags', [])
                    }
                    
                    if self.primary_ip in ips_v4:
                        self.primary_interface = name
            except json.JSONDecodeError:
                pass
        except Exception: pass

    def _detect_windows_interfaces(self):
        # Basic detection using netsh (since ifaddr/netifaces might not be available)
        try:
            # Detect Loopback Name
            cmd = ["netsh", "interface", "ipv4", "show", "interfaces"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if "Loopback" in line:
                    parts = re.split(r'\s{2,}', line.strip())
                    if len(parts) >= 5:
                        name = parts[4]
                        self.interfaces[name] = {
                            'ip_v4': ['127.0.0.1'],
                            'ip_v6': [],
                            'type': 'loopback',
                            'flags': ['LOOPBACK', 'UP']
                        }
            
            # Detect Primary Interface (using self.primary_ip found via socket)
            if self.primary_ip and self.primary_ip != '127.0.0.1':
                cmd2 = ["netsh", "interface", "ipv4", "show", "addresses"]
                r2 = subprocess.run(cmd2, capture_output=True, text=True)
                current_iface = None
                for line in r2.stdout.splitlines():
                    if "Configuration for interface" in line:
                        current_iface = line.split('"')[1]
                    if self.primary_ip in line and current_iface:
                        self.primary_interface = current_iface
                        self.interfaces[current_iface] = {
                            'ip_v4': [self.primary_ip],
                            'ip_v6': [],
                            'type': 'ethernet',
                            'flags': ['UP', 'MULTICAST']
                        }
                        break
        except Exception: 
            pass

    def _try_setup_vnet(self):
        """Attempt to set up VNet if not already present."""
        # Quick check: is br0 already there?
        if 'br0' in self.interfaces:
            return  # VNet likely already set up
        
        if not self.can_sudo and not self.is_root:
            return  # Can't set up without privileges
            
        script_path = os.path.join(os.path.dirname(__file__), "scripts", "setup_vnet.sh")
        if not os.path.exists(script_path):
            return
        
        cmd = ["sudo", "bash", script_path] if self.can_sudo and not self.is_root else ["bash", script_path]
        print(f"[ENV] VNet not detected. Setting up: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, timeout=30)
            # Refresh interface detection after setup
            self._detect_network_interfaces()
        except Exception as e:
            print(f"[ENV] VNet setup failed: {e}")

    def _detect_vnet(self):
        if self.os_type == 'Linux':
            # Check for br0
            if 'br0' in self.interfaces:
                self.has_vnet = True
            
            # Check namespaces
            if self.can_sudo or self.is_root:
                cmd = ['sudo', '-n', 'ip', 'netns', 'list'] if self.can_sudo and not self.is_root else ['ip', 'netns', 'list']
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True)
                    for line in r.stdout.splitlines():
                        ns = line.split()[0]
                        self.vnet_namespaces.append(ns)
                        
                        # Deep inspection — returns rich topology info
                        ns_info = self._inspect_namespace(ns)
                        self.vnet_topology[ns] = ns_info
                        
                        # Build legacy interface map for backward compat
                        legacy_map = {}
                        for iface_name, iface_data in ns_info.items():
                            if iface_data.get('ipv4'):
                                legacy_map[iface_data['ipv4']] = iface_name
                        self.vnet_interface_map[ns] = legacy_map
                except Exception: pass
            
            # Derive VNet capabilities from topology
            for ns, topology in self.vnet_topology.items():
                for iface_name, iface_data in topology.items():
                    if iface_data.get('ipv6'):
                        self.vnet_has_ipv6 = True
                    if 'MULTICAST' in iface_data.get('flags', []):
                        self.vnet_has_multicast = True

    def _inspect_namespace(self, ns):
        """
        Inspect a network namespace and return rich interface info.
        
        Returns:
            dict: { "veth0": { "ipv4": "10.0.1.1", "ipv6": "fd00:1::1", "flags": [...] }, ... }
        """
        result = {}
        cmd_prefix = ['sudo', '-n', 'ip', 'netns', 'exec', ns] if self.can_sudo and not self.is_root else ['ip', 'netns', 'exec', ns]
        try:
            r = subprocess.run(cmd_prefix + ['ip', '-j', 'addr'], capture_output=True, text=True)
            data = json.loads(r.stdout)
            for iface in data:
                name = iface['ifname']
                if name == 'lo':
                    continue  # Skip loopback in VNet inspection
                
                ipv4 = None
                ipv6 = None
                for addr in iface.get('addr_info', []):
                    if addr['family'] == 'inet' and not ipv4:
                        ipv4 = addr['local']
                    elif addr['family'] == 'inet6' and not ipv6:
                        # Prefer non-link-local addresses
                        ip = addr['local']
                        if not ip.startswith('fe80'):
                            ipv6 = ip
                
                # If only link-local IPv6, use it as fallback
                if not ipv6:
                    for addr in iface.get('addr_info', []):
                        if addr['family'] == 'inet6':
                            ipv6 = addr['local']
                            break
                
                result[name] = {
                    'ipv4': ipv4,
                    'ipv6': ipv6,
                    'flags': iface.get('flags', [])
                }
        except Exception: pass
        return result

    def _detect_capabilities(self):
        # IPv4 check
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.close()
            self.has_ipv4 = True
        except Exception:
            self.has_ipv4 = False
        
        # IPv6 check
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s.close()
            self.has_ipv6 = True
        except Exception:
            self.has_ipv6 = False
        
        # Multicast check — assumes available (validated by runtime binding)
        self.supports_multicast = True
        
        # Windows Loopback MCAST
        if self.os_type == 'Windows':
            self.loopback_multicast_ok = True

    def setup_vnet(self):
        """Attempts to set up the virtual network if not present."""
        if self.has_vnet: return True
        if self.os_type != 'Linux': return False
        if not self.can_sudo and not self.is_root: return False
        
        script_path = os.path.join(os.path.dirname(__file__), "scripts", "setup_vnet.sh")
        if not os.path.exists(script_path): return False
        
        cmd = ["sudo", "bash", script_path] if self.can_sudo and not self.is_root else ["bash", script_path]
        print(f"Setting up VNet: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
            self._detect_network_interfaces()
            self._detect_vnet() # Refresh detection
            return self.has_vnet
        except Exception as e:
            print(f"VNet setup failed: {e}")
            return False

    def teardown_vnet(self):
        """Attempts to tear down the virtual network."""
        if self.os_type != 'Linux': return
        if not self.can_sudo and not self.is_root: return

        script_path = os.path.join(os.path.dirname(__file__), "scripts", "teardown_vnet.sh")
        if os.path.exists(script_path):
             cmd = ["sudo", "bash", script_path] if self.can_sudo and not self.is_root else ["bash", script_path]
             try: subprocess.run(cmd, check=True)
             except Exception: pass
        else:
             # Manual cleanup
             for ns in self.vnet_namespaces:
                 cmd = ["sudo", "ip", "netns", "del", ns] if self.can_sudo and not self.is_root else ["ip", "netns", "del", ns]
                 try: subprocess.run(cmd)
                 except Exception: pass

    def get_vnet_ip(self, ns, iface='veth0', version=4):
        """
        Get an IP address from a VNet namespace interface.
        
        Args:
            ns: Namespace name (e.g., 'ns_ecu1')
            iface: Interface name within the namespace (default: 'veth0')
            version: 4 for IPv4, 6 for IPv6
            
        Returns:
            str or None: The IP address, or None if not available
        """
        ns_data = self.vnet_topology.get(ns, {})
        iface_data = ns_data.get(iface, {})
        if version == 6:
            return iface_data.get('ipv6')
        return iface_data.get('ipv4')
    
    def get_vnet_iface_for_ip(self, ns, ip):
        """
        Given a namespace and an IP, return the interface name that has that IP.
        
        Args:
            ns: Namespace name
            ip: IP address to look up
            
        Returns:
            str or None: Interface name, or None if not found
        """
        ns_data = self.vnet_topology.get(ns, {})
        for iface_name, iface_data in ns_data.items():
            if iface_data.get('ipv4') == ip or iface_data.get('ipv6') == ip:
                return iface_name
        return None

    def to_dict(self):
        return {
            'os': self.os_type,
            'is_wsl': self.is_wsl,
            'can_sudo': self.can_sudo,
            'primary_interface': self.primary_interface,
            'primary_ip': self.primary_ip,
            'interfaces': {name: {'type': d['type'], 'ipv4': d.get('ip_v4', []), 'ipv6': d.get('ip_v6', [])} for name, d in self.interfaces.items()},
            'vnet': {
                'available': self.has_vnet,
                'namespaces': self.vnet_namespaces,
                'topology': self.vnet_topology,
                'has_ipv6': self.vnet_has_ipv6,
                'has_multicast': self.vnet_has_multicast,
            },
            'capabilities': {
                'ipv4': self.has_ipv4,
                'ipv6': self.has_ipv6,
                'multicast': self.supports_multicast,
            }
        }

if __name__ == "__main__":
    env = NetworkEnvironment()
    env.detect()
    print(json.dumps(env.to_dict(), indent=2))
