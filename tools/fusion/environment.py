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
        self.interfaces = {} # name -> {ip_v4: [], ip_v6: [], type: 'loopback'|'ethernet'|'bridge'|'veth'}
        self.primary_interface = None
        self.primary_ip = None
        
        # VNet
        self.has_vnet = False
        self.vnet_namespaces = [] # List of ns names
        self.vnet_interface_map = {} # ns_name -> {ip -> iface_name}
        
        # Capabilities
        self.has_ipv4 = True
        self.has_ipv6 = False
        self.supports_multicast = False
        self.supports_broadcast = False
        self.loopback_multicast_ok = True 
        
    def detect(self):
        self._detect_os()
        self._detect_privileges()
        self._detect_network_interfaces()
        self._detect_vnet()
        self._detect_capabilities()

    def _detect_os(self):
        if self.os_type == 'Linux':
            try:
                with open('/proc/version', 'r') as f:
                    content = f.read().lower()
                    if 'microsoft' in content:
                        self.is_wsl = True
                        self.distro = "WSL"
            except: pass
        elif self.os_type == 'Windows':
            pass
        # TODO: Android/QNX detection stubs

    def _detect_privileges(self):
        if self.os_type != 'Windows':
            if self.is_root:
                self.can_sudo = True
            else:
                # Check passwordless sudo
                try:
                    r = subprocess.run(['sudo', '-n', 'true'], capture_output=True)
                    self.can_sudo = (r.returncode == 0)
                except:
                    self.can_sudo = False

    def _detect_network_interfaces(self):
        # Universal approach: use socket to find primary, subprocess for details
        try:
            # Find primary interface via routing
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            self.primary_ip = s.getsockname()[0]
            s.close()
        except:
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
                # Fallback to text parsing (omitted for brevity, assume 'ip -j' exists on modern Linux)
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
                            'type': 'loopback'
                        }
            
            # Detect Primary Interface (using self.primary_ip found via socket)
            if self.primary_ip and self.primary_ip != '127.0.0.1':
                # We need to find the interface name for this IP. 
                # parsing `ipconfig` is messy. `netsh interface ipv4 show addresses` might be better.
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
                            'type': 'ethernet' # Assumption
                        }
                        break
        except Exception: 
            pass

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
                        
                        # Deep inspection
                        self.vnet_interface_map[ns] = self._inspect_namespace(ns)
                except: pass

    def _inspect_namespace(self, ns):
        # Return {ip: iface_name}
        mapping = {}
        cmd = ['sudo', '-n', 'ip', 'netns', 'exec', ns, 'ip', '-j', 'addr'] if self.can_sudo and not self.is_root else ['ip', 'netns', 'exec', ns, 'ip', '-j', 'addr']
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(r.stdout)
            for iface in data:
                name = iface['ifname']
                for addr in iface.get('addr_info', []):
                    if addr['family'] == 'inet':
                        mapping[addr['local']] = name
        except: pass
        return mapping

    def _detect_capabilities(self):
        # IPv6 check
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s.close()
            self.has_ipv6 = True
        except: self.has_ipv6 = False
        
        # Multicast check
        # ... logic from utils ...
        self.supports_multicast = True # Supported on Windows via Loopback (using recent runtime fixes)
        
        # Windows Loopback MCAST
        if self.os_type == 'Windows':
            self.loopback_multicast_ok = True # Enabled for verification

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
            self._detect_vnet() # Refresh detection
            return self.has_vnet
        except Exception as e:
            print(f"VNet setup failed: {e}")
            return False

    def teardown_vnet(self):
        """Attempts to tear down the virtual network."""
        if self.os_type != 'Linux': return
        if not self.can_sudo and not self.is_root: return

        # Ideally call teardown_vnet.sh, but for now just delete namespaces?
        # Assuming teardown script exists or we manually clean up.
        # Check for teardown script
        script_path = os.path.join(os.path.dirname(__file__), "scripts", "teardown_vnet.sh")
        if os.path.exists(script_path):
             cmd = ["sudo", "bash", script_path] if self.can_sudo and not self.is_root else ["bash", script_path]
             try: subprocess.run(cmd, check=True)
             except: pass
        else:
             # Manual cleanup
             for ns in self.vnet_namespaces:
                 cmd = ["sudo", "ip", "netns", "del", ns] if self.can_sudo and not self.is_root else ["ip", "netns", "del", ns]
                 try: subprocess.run(cmd)
                 except: pass
             # TODO: Delete bridges br0/br1?

    def to_dict(self):
        return {
            'os': self.os_type,
            'is_wsl': self.is_wsl,
            'can_sudo': self.can_sudo,
            'primary_interface': self.primary_interface,
            'primary_ip': self.primary_ip,
            'vnet_namespaces': self.vnet_namespaces,
            'vnet_interface_map': self.vnet_interface_map,
            'capabilities': {
                'ipv6': self.has_ipv6,
                'multicast': self.supports_multicast
            }
        }

if __name__ == "__main__":
    env = NetworkEnvironment()
    env.detect()
    print(json.dumps(env.to_dict(), indent=2))
