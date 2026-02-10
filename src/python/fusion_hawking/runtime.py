import socket
import struct
import threading
import time
import select
import json
import ipaddress
import re
import platform
import subprocess
from typing import Dict, Tuple, Optional
from enum import IntEnum
from .logger import LogLevel, ConsoleLogger, ILogger


class MessageType(IntEnum):
    """SOME/IP Message Types as defined in AUTOSAR spec [PRS_SOMEIP_00034]"""
    REQUEST = 0x00
    REQUEST_NO_RETURN = 0x01
    NOTIFICATION = 0x02
    REQUEST_WITH_TP = 0x20
    REQUEST_NO_RETURN_WITH_TP = 0x21
    NOTIFICATION_WITH_TP = 0x22
    RESPONSE = 0x80
    ERROR = 0x81
    RESPONSE_WITH_TP = 0xA0
    ERROR_WITH_TP = 0xA1


class ReturnCode(IntEnum):
    """SOME/IP Return Codes as defined in AUTOSAR spec [PRS_SOMEIP_00043]"""
    OK = 0x00
    NOT_OK = 0x01
    UNKNOWN_SERVICE = 0x02
    UNKNOWN_METHOD = 0x03
    NOT_READY = 0x04
    NOT_REACHABLE = 0x05
    TIMEOUT = 0x06
    WRONG_PROTOCOL_VERSION = 0x07
    WRONG_INTERFACE_VERSION = 0x08
    MALFORMED_MESSAGE = 0x09
    WRONG_MESSAGE_TYPE = 0x0A
    E2E_REPEATED = 0x0B
    E2E_WRONG_SEQUENCE = 0x0C
    E2E_NOT_AVAILABLE = 0x0D
    E2E_NO_NEW_DATA = 0x0E


class SessionIdManager:
    """Manages session IDs per (service_id, method_id) pair"""
    def __init__(self):
        self._counters: Dict[Tuple[int, int], int] = {}
    
    def next_session_id(self, service_id: int, method_id: int) -> int:
        key = (service_id, method_id)
        if key not in self._counters:
            self._counters[key] = 1
        current = self._counters[key]
        self._counters[key] = (current % 0xFFFF) + 1  # Wrap at 0xFFFF, skip 0
        return current
    
    def reset(self, service_id: int, method_id: int):
        self._counters[(service_id, method_id)] = 1
    
    def reset_all(self):
        self._counters.clear()


class RequestHandler:
    def get_service_id(self) -> int:
        raise NotImplementedError()
    def get_major_version(self) -> int:
        return 1
    def get_minor_version(self) -> int:
        return 0
    def handle(self, header: Dict, payload: bytes) -> bytes:
        raise NotImplementedError()

import json
import os

class SomeIpRuntime:
    @staticmethod
    def _is_local_unicast(ip_str):
        try:
            obj = ipaddress.ip_address(ip_str)
            return not obj.is_multicast
        except ValueError:
            return False

    def _infer_ips_from_services(self, services_dict):
        for svc in services_dict.values():
            ep_name = svc.get('endpoint')
            if ep_name and ep_name in self.endpoints:
                ep = self.endpoints[ep_name]
                ep_ip = ep.get('ip', '')
                if not ep_ip or not self._is_local_unicast(ep_ip): continue
                try:
                    obj = ipaddress.ip_address(ep_ip)
                    if obj.version == 4 and not self.interface_ip:
                        self.interface_ip = ep_ip
                    elif obj.version == 6 and not self.interface_ip_v6:
                        self.interface_ip_v6 = ep_ip
                except: pass

    def __init__(self, config_path: str, instance_name: str, logger: Optional[ILogger] = None):
        self.logger = logger or ConsoleLogger()
        self.services: Dict[int, RequestHandler] = {}
        self.offered_services = [] # list of (sid, iid, port)
        self.remote_services: Dict[Tuple[int, int], Tuple[str, int]] = {} # (sid, major) -> endpoint
        self.running = False
        self.thread = None
        self.last_offer_time = 0
        
        self.config, self.endpoints = self._load_config(config_path, instance_name)
        
        self.interface_ip = None
        self.interface_ip_v6 = None
        
        if self.config and 'providing' in self.config:
            # Find first v4 and v6 endpoints that are not multicast
            for svc in self.config['providing'].values():
                ep_name = svc.get('endpoint')
                if ep_name and ep_name in self.endpoints:
                    ep = self.endpoints[ep_name]
                    ep_ip = ep.get('ip', '')
                    if not ep_ip or not self._is_local_unicast(ep_ip):
                        continue
                        
                    ip_obj = ipaddress.ip_address(ep_ip)
                    if ip_obj.version == 4:
                        self.interface_ip = ep_ip
                    elif ip_obj.version == 6:
                        self.interface_ip_v6 = ep_ip
        
        # Determine networking params from first providing service endpoint
        bind_port = 0
        self.protocol = "udp" # Default
        
        if self.config and 'providing' in self.config:
            for svc in self.config['providing'].values():
                ep_name = svc.get('endpoint')
                if ep_name and ep_name in self.endpoints:
                    ep = self.endpoints[ep_name]
                    
                    if 'interface' not in ep or not ep['interface']:
                        raise ValueError(f"Mandatory configuration 'interface' missing for endpoint '{ep_name}'")

                    self.protocol = ep.get('protocol', 'udp').lower()
                    bind_port = ep.get('port', 0)
                    
                    if ep.get('version') == 4:
                        self.interface_ip = ep.get('ip')
                    elif ep.get('version') == 6:
                        self.interface_ip_v6 = ep.get('ip')
                    
                    if bind_port != 0:
                        break # Found our primary bind target

        if self.config:
            if not self.interface_ip or not self.interface_ip_v6:
                self._infer_ips_from_services(self.config.get('providing', {}))
            if not self.interface_ip or not self.interface_ip_v6:
                self._infer_ips_from_services(self.config.get('required', {}))

        # NO hardcoded fallbacks to 127.0.0.1 or ::1 here as per Project Rules.
        # IP must come from configuration (providing or required endpoints).

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try: self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError: pass
        self.sock_v6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.sock_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try: self.sock_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError: pass
        try:
            self.sock.bind(('0.0.0.0', bind_port))
            self.sock_v6.bind(('::', bind_port))
        except Exception:
            self.logger.log(LogLevel.WARN, "Runtime", f"Failed to bind {bind_port}, using ephemeral")
            self.sock.close()
            self.sock_v6.close()
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try: self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError: pass
            self.sock.bind(('0.0.0.0', 0))
            self.sock_v6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            self.sock_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try: self.sock_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError: pass
            self.sock_v6.bind(('::', 0))
            
        self.port = self.sock.getsockname()[1]

        self.tcp_listener = None
        self.tcp_listener_v6 = None
        self.tcp_clients = [] # list of (socket, addr)
        
        if self.protocol == "tcp":
            self.tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try: self.tcp_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError: pass
            self.tcp_listener.bind((self.interface_ip, bind_port))
            self.tcp_listener.listen(5)
            self.tcp_listener.setblocking(False)
            
            # If dynamic port was used, retrieve it so v6 binds to the same one
            if bind_port == 0:
                bind_port = self.tcp_listener.getsockname()[1]

            self.tcp_listener_v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            self.tcp_listener_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try: self.tcp_listener_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError: pass
                
            # Windows/Some OSs require V6ONLY=1 for dual binding on same port to work without conflict
            # Python usually defaults V6ONLY to 1 on Windows, but let's be explicit if we want separate sockets
            try: self.tcp_listener_v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            except OSError: pass

            self.tcp_listener_v6.bind((self.interface_ip_v6, bind_port))
            self.tcp_listener_v6.listen(5)
            self.tcp_listener_v6.setblocking(False)
            self.port = bind_port

        self.logger.log(LogLevel.INFO, "Runtime", f"Initialized '{instance_name}' on port {self.port} ({self.protocol}) [Dual-Stack]")
        
        # SD Socket
        self.sd_pub_port = 30490
        self.sd_multicast_ip = None
        self.sd_multicast_ip_v6 = None
        
        if self.config and 'sd' in self.config:
            sd_cfg = self.config['sd']
            self.sd_pub_port = sd_cfg.get('multicast_port', 30490)
            
            # Resolve SD Multicast Endpoint
            if 'multicast_endpoint' in sd_cfg:
                ep_name = sd_cfg['multicast_endpoint']
                if ep_name in self.endpoints:
                    ep = self.endpoints[ep_name]
                    if 'interface' not in ep or not ep['interface']:
                         raise ValueError(f"Mandatory configuration 'interface' missing for SD Endpoint '{ep_name}'")
                    
                    self.sd_multicast_ip = ep.get('ip')
                    if not self.sd_multicast_ip:
                         raise ValueError(f"Mandatory 'ip' missing for SD Endpoint '{ep_name}'")
                    self.sd_pub_port = ep.get('port', self.sd_pub_port)
                    self.sd_interface = ep.get('interface')

            if 'multicast_endpoint_v6' in sd_cfg:
                ep_name = sd_cfg['multicast_endpoint_v6']
                if ep_name in self.endpoints:
                    ep = self.endpoints[ep_name]
                    if 'interface' not in ep or not ep['interface']:
                         raise ValueError(f"Mandatory configuration 'interface' missing for SD Endpoint '{ep_name}'")
                    
                    self.sd_multicast_ip_v6 = ep.get('ip')
                    self.sd_pub_port = ep.get('port', self.sd_pub_port)
                    self.sd_interface_v6 = ep.get('interface')
        
        if not self.sd_multicast_ip:
            raise ValueError("SD Multicast IPv4 IP not configured in instances/sd.")
        
        # Validate that we have a v4 interface IP if v4 SD is enabled
        if self.sd_multicast_ip and not self.interface_ip:
            raise ValueError("SD Multicast (v4) is enabled but no IPv4 unicast interface IP found in configuration.")
        
        self.request_timeout = self.config.get('sd', {}).get('request_timeout_ms', 2000) / 1000.0
        self.offer_interval = self.config.get('sd', {}).get('cycle_offer_ms', 500) / 1000.0
        self.multicast_hops = self.config.get('sd', {}).get('multicast_hops', 1)

        # IPv4 SD
        self.sd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try: self.sd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError: pass
        
        # Bind to wildcard for multicast listener (required on Windows for receiving multicast on specific group/port)
        self.sd_sock.bind(('0.0.0.0', self.sd_pub_port))
        
        mreq = struct.pack("4s4s", socket.inet_aton(self.sd_multicast_ip), socket.inet_aton(self.interface_ip))
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        # Removed fallback to 0.0.0.0 as per user request for strictness.
        
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.interface_ip))
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.multicast_hops)
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        # IPv6 SD
        self.sd_sock_v6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.sd_sock_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try: self.sd_sock_v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError: pass
        self.sd_sock_v6.bind(('::', self.sd_pub_port))
        
        if self.sd_multicast_ip_v6:
            if not self.interface_ip_v6:
                self.logger.log(LogLevel.WARN, "Runtime", "SD Multicast (v6) is enabled but no IPv6 unicast interface IP found in configuration. SD v6 will be disabled.")
            else:
                try:
                    mreq_v6 = struct.pack("16si", socket.inet_pton(socket.AF_INET6, self.sd_multicast_ip_v6), 0)
                    self.sd_sock_v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq_v6)
                    
                    # Resolve index dynamically from friendly name (config value)
                    iface_name = getattr(self, 'sd_interface_v6', None) or getattr(self, 'sd_interface', None)
                    iface_idx = self._resolve_interface_index(iface_name)
    
                    self.sd_sock_v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, iface_idx)
                    self.sd_sock_v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, self.multicast_hops)
                    self.sd_sock_v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)
                except OSError as e:
                    self.logger.log(LogLevel.WARN, "Runtime", f"Failed to setup SD v6 socket: {e}")
        else:
             self.logger.log(LogLevel.WARN, "SD", "IPv6 Multicast IP not configured, skipping join.")
        
        self.sock.setblocking(False)
        self.sock_v6.setblocking(False)
        self.sd_sock.setblocking(False)
        self.sd_sock_v6.setblocking(False)
        self.pending_requests: Dict[Tuple[int, int, int], threading.Event] = {} # (sid, meth, sess) -> event
        self.request_results: Dict[Tuple[int, int, int], bytes] = {}
        self.session_manager = SessionIdManager()

    def _resolve_interface_index(self, interface_name: str) -> int:
        """Resolve interface name to index, handling Windows friendly names"""
        if not interface_name:
            return 0
            
        # Try standard socket API first (works on Linux and modern Windows with UUIDs)
        try:
            return socket.if_nametoindex(interface_name)
        except OSError:
            pass
            
        # Fallback for Windows friendly names (e.g. "Wi-Fi", "Ethernet")
        if platform.system() == "Windows":
            try:
                # Use netsh to find the index
                cmd = ["netsh", "interface", "ipv4", "show", "interfaces"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                # Parse output:
                # Idx     Met         MTU          State          Name
                # ---  ----------  ----------  ------------  ---------------------------
                #   1          75  4294967295  connected     Loopback Pseudo-Interface 1
                for line in result.stdout.splitlines():
                    if interface_name in line:
                        # Extract the first number (Idx)
                        match = re.search(r"^\s*(\d+)", line)
                        if match:
                            return int(match.group(1))
            except Exception as e:
                self.logger.log(LogLevel.WARN, "Runtime", f"Failed to resolve interface index for '{interface_name}' via netsh: {e}")
                
        self.logger.log(LogLevel.WARN, "Runtime", f"Could not resolve interface index for '{interface_name}', defaulting to 0")
        return 0

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        # Wake up select
        try:
            ws = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ws.sendto(b'', (self.interface_ip, self.port))
            ws.close()
        except Exception: pass
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            
        if self.sock:
            self.sock.close()
            self.sock = None
        if self.sd_sock:
            self.sd_sock.close()
            self.sd_sock = None

    def _load_config(self, path, name):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return data['instances'].get(name, {}), data.get('endpoints', {})
        except Exception as e:
            print(f"Config Load Error ({path}): {e}")
            return {}, {}

    def offer_service(self, alias: str, handler: RequestHandler):
        sid = handler.get_service_id()
        instance_id = 1
        endpoint_ip = self.interface_ip
        endpoint_ip_v6 = self.interface_ip_v6
        port = self.port
        multicast_ip = None
        multicast_port = None

        if self.config and 'providing' in self.config:
            svc_cfg = self.config['providing'].get(alias)
            if svc_cfg:
                sid = svc_cfg.get('service_id', sid)
                instance_id = svc_cfg.get('instance_id', instance_id)
                
                endpoint_name = svc_cfg.get('endpoint')
                if endpoint_name and endpoint_name in self.endpoints:
                    ep = self.endpoints[endpoint_name]
                    endpoint_ip = ep.get('ip', endpoint_ip)
                    port = ep.get('port', 0)
                    if port == 0:
                        port = self.port
                    if ep.get('version') == 6:
                        endpoint_ip_v6 = ep.get('ip', endpoint_ip_v6)

                multicast_name = svc_cfg.get('multicast')
                if multicast_name and multicast_name in self.endpoints:
                    m_ep = self.endpoints[multicast_name]
                    multicast_ip = m_ep.get('ip')
                    multicast_port = m_ep.get('port')

        self.services[sid] = handler
        self.offered_services.append((sid, instance_id, handler.get_major_version(), handler.get_minor_version(), port, endpoint_ip, endpoint_ip_v6, multicast_ip, multicast_port))
        self._send_offer(sid, instance_id, handler.get_major_version(), handler.get_minor_version(), port, endpoint_ip, endpoint_ip_v6, multicast_ip, multicast_port)
        self.logger.log(LogLevel.INFO, "Runtime", f"Offered {alias} (0x{sid:04x}) v{handler.get_major_version()}.{handler.get_minor_version()} on port {port}")

    def get_client(self, service_name_in_config: str, client_cls, timeout=5.0) -> Optional[object]:
        """
        Factory to create a client proxy for a required service.
        Blocks until service is discovered via SD or timeout.
        """
        if not self.config or 'required' not in self.config:
            return None
        
        req_cfg = self.config['required'].get(service_name_in_config)
        if not req_cfg:
            return None
            
        service_id = req_cfg.get('service_id')
        major_version = req_cfg.get('major_version', 1) # Default to 1 if missing?
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            key = (service_id, major_version)
            if key in self.remote_services:
                # Found it
                # Create instance
                return client_cls(self, service_name_in_config)
            time.sleep(0.1)
            
        return None

    def _wait_for_service(self, service_id: int, alias: str, timeout: float = 5.0) -> Optional[Tuple[str, int]]:
        """Wait for a service to be discovered via SD, with timeout."""
        import time
        start = time.time()
        poll_interval = 0.1
        
        while time.time() - start < timeout:
            # Process any pending SD packets
            self._poll_sd()
            
            # Check if service is available
            if service_id in self.remote_services:
                endpoint = self.remote_services[service_id]
                proto_str = endpoint[2] if len(endpoint) > 2 else "unknown"
                self.logger.log(LogLevel.INFO, "Runtime", f"Discovered '{alias}' (0x{service_id:04x}) at {endpoint[0]}:{endpoint[1]} via {proto_str}")
                return endpoint
            
            time.sleep(poll_interval)
        
        self.logger.log(LogLevel.WARN, "Runtime", f"Timeout waiting for '{alias}' (0x{service_id:04x})")
        return None

    def _poll_sd(self):
        """Process pending SD packets without blocking."""
        import select
        readable, _, _ = select.select([self.sd_sock], [], [], 0)
        for s in readable:
            try:
                data, addr = s.recvfrom(1500)
                self.logger.log(LogLevel.DEBUG, "SD", f"Packet from {addr} len={len(data)}")
                self._handle_sd_packet(data, addr)
            except Exception:
                pass

    def _handle_sd_packet(self, data: bytes, addr: Tuple):
        """Parse and handle an SD packet. [PRS_SOMEIPSD_00016]"""
        if len(data) < 20: return

        
        # Header (12 bytes) + Entries Len (4 bytes) -> Start of Entries at 12?
        # Header: Flags(1)+Res(3)+Len(4) = 8 bytes.
        # Wait, My sending code above: Flags(4) + EntriesLen(4). So Header is 8 bytes.
        # Entries start at index 12? No, 8 bytes of header. 
        # C++ impl said: Flags(1)+Res(3)+Len(4).
        # Python buffer `data` in `_run`:
        # `recvfrom(1500)`. This returns SOME/IP Message (Header 16 bytes + Payload).
        # My `_run` loop: `if len(data) >= 16: ... elif s == self.sd_sock:`.
        # SD Socket receives raw SD or SOME/IP-SD? 
        # SD port 30490. Packets have SOME/IP Header (16 bytes).
        # So `data` has 16 bytes SOME/IP Header.
        # Payload starts at 16.
        # SD Header inside Payload: Flags(1)+Res(3)+LengthOfEntries(4).
        # So Entries start at 16 + 8 = 24.
        # Let's verify `send_offer` above.
        # `someip_header` (16 bytes) + `sd_payload` (Flags...EntriesLen...Entries).
        # So yes, offsets need adjustment.
        
        # Existing code: `sid = struct.unpack(">H", data[28:30])[0]`
        # 28 = 16 (Header) + 8 (SD Header) + 4 (Type, Idx, Opts). 
        # SvcID is at offset 4 of Entry.
        # So 24 + 4 = 28. Correct.
        
        offset = 16 # Start of SD Payload
        if len(data) < offset + 8: return
        
        flags = data[offset]
        len_entries = struct.unpack(">I", data[offset+4:offset+8])[0]
        entries_start = offset + 8
        entries_end = entries_start + len_entries
        
        if len(data) < entries_end: return
        
        current = entries_start
        while current + 16 <= entries_end:
            entry_type = data[current]
            index1 = data[current+1]
            index2 = data[current+2]
            num_opts_byte = data[current+3]
            num_opts_1 = (num_opts_byte >> 4) & 0x0F
            n_opts_2 = num_opts_byte & 0x0F
            
            sid = struct.unpack(">H", data[current+4:current+6])[0]
            iid = struct.unpack(">H", data[current+6:current+8])[0]
            ttl_raw = struct.unpack(">I", data[current+8:current+12])[0]
            major_ver = (ttl_raw >> 24) & 0xFF
            ttl = ttl_raw & 0xFFFFFF 
            min_ver = struct.unpack(">I", data[current+12:current+16])[0]
            
            # Options Handling (Simplified: Scan all options after entries)
            options_start = entries_end + 4 # Skip Options Len
            
            if entry_type == 0x01: # OfferService
                parsed_opts = []
                opt_ptr = options_start
                if len(data) > options_start:
                    try:
                        len_opts = struct.unpack(">I", data[entries_end:entries_end+4])[0]
                        opts_end = options_start + len_opts
                        while opt_ptr + 3 <= opts_end and opt_ptr < len(data):
                            l = struct.unpack(">H", data[opt_ptr:opt_ptr+2])[0]
                            t = data[opt_ptr+2]
                            if t == 0x04: # IPv4
                                ip_raw = data[opt_ptr+4:opt_ptr+8]
                                ip_str = f"{ip_raw[0]}.{ip_raw[1]}.{ip_raw[2]}.{ip_raw[3]}"
                                p = struct.unpack(">H", data[opt_ptr+10:opt_ptr+12])[0]
                                proto_id = data[opt_ptr+9]
                                proto = "tcp" if proto_id == 0x06 else "udp"
                                parsed_opts.append( (ip_str, p, proto) )
                            elif t == 0x06: # IPv6
                                ip_raw = data[opt_ptr+4:opt_ptr+20]
                                ip_str = socket.inet_ntop(socket.AF_INET6, ip_raw)
                                p = struct.unpack(">H", data[opt_ptr+22:opt_ptr+24])[0]
                                proto_id = data[opt_ptr+21]
                                proto = "tcp" if proto_id == 0x06 else "udp"
                                parsed_opts.append( (ip_str, p, proto) )
                            else:
                                parsed_opts.append(None)
                            opt_ptr += 2 + l # Length field includes Type, so advance by Len Field (2) + Len Value
                    except: pass
                    
                if ttl > 0:
                    endpoint = None
                    if num_opts_1 > 0 and index1 < len(parsed_opts):
                        endpoint = parsed_opts[index1]
                    
                    if not endpoint:
                        # Fallback: check options for ANY endpoint
                        for opt in parsed_opts:
                            if opt:
                                endpoint = opt
                                break
                    
                    self.logger.log(LogLevel.DEBUG, "SD", f"Parsed Entry: SID={sid} IID={iid} TTL={ttl}")
                    if endpoint is None:
                         self.logger.log(LogLevel.WARN, "SD", f"Offer 0x{sid:04x} from {addr} has no usable endpoint. Parsed: {parsed_opts}")

                    if endpoint and endpoint[0] not in ('0.0.0.0', '::'):
                        endpoint = (endpoint[0], endpoint[1], endpoint[2]) # ensure tuple

                        # Key by (sid, major_ver)
                        key = (sid, major_ver)
                        changed = True
                        if key in self.remote_services:
                             if self.remote_services[key] == endpoint:
                                 changed = False
                        
                        if changed:
                            self.remote_services[key] = endpoint
                            self.logger.log(LogLevel.DEBUG, "SD", f"Discovered 0x{sid:04x} v{major_ver} at {endpoint[0]}:{endpoint[1]}")
                        
            elif entry_type == 0x06: # SubscribeEventgroup
                parsed_opts = []
                opt_ptr = options_start
                if len(data) > options_start:
                    try:
                        len_opts = struct.unpack(">I", data[entries_end:entries_end+4])[0]
                        opts_end = options_start + len_opts
                        while opt_ptr + 3 <= opts_end and opt_ptr < len(data):
                            l = struct.unpack(">H", data[opt_ptr:opt_ptr+2])[0]
                            t = data[opt_ptr+2]
                            if t == 0x04: # IPv4
                                ip_raw = data[opt_ptr+4:opt_ptr+8]
                                ip_str = f"{ip_raw[0]}.{ip_raw[1]}.{ip_raw[2]}.{ip_raw[3]}"
                                p = struct.unpack(">H", data[opt_ptr+10:opt_ptr+12])[0]
                                proto_id = data[opt_ptr+9]
                                proto = "tcp" if proto_id == 0x06 else "udp"
                                parsed_opts.append( (ip_str, p, proto) )
                            elif t == 0x06: # IPv6
                                ip_raw = data[opt_ptr+4:opt_ptr+20]
                                ip_str = socket.inet_ntop(socket.AF_INET6, ip_raw)
                                p = struct.unpack(">H", data[opt_ptr+22:opt_ptr+24])[0]
                                proto_id = data[opt_ptr+21]
                                proto = "tcp" if proto_id == 0x06 else "udp"
                                parsed_opts.append( (ip_str, p, proto) )
                            else:
                                parsed_opts.append(None)
                            opt_ptr += 3 + l
                    except: pass

                if num_opts_1 > 0 and index1 < len(parsed_opts):
                    base_endpoint = parsed_opts[index1]

                is_offered = any(s[0] == sid for s in self.offered_services)
                
                if is_offered and ttl > 0 and base_endpoint:
                     # Send ACK
                     eventgroup_id = min_ver >> 16
                     ack_payload = bytearray([0x80, 0, 0, 0])
                     ack_payload += struct.pack(">I", 16)
                     ack_payload += struct.pack(">BBBBHHII", 0x07, 0, 0, 0, sid, iid, ttl | (1<<24), min_ver)
                     ack_payload += struct.pack(">I", 0) 
                     
                     plen = len(ack_payload) + 8
                     sh = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, plen, 0, 1, 1, 1, 2, 0)
                     
                     # Detect if source was via IPv6
                     is_ipv6_src = ":" in base_endpoint[0]
                     if is_ipv6_src and self.sd_multicast_ip_v6:
                        self.sd_sock_v6.sendto(sh + ack_payload, (self.sd_multicast_ip_v6, self.sd_pub_port))
                     elif not is_ipv6_src and self.sd_multicast_ip:
                        self.sd_sock.sendto(sh + ack_payload, (self.sd_multicast_ip, self.sd_pub_port))
                    
            elif entry_type == 0x07: # SubscribeEventgroupAck
                eventgroup_id = min_ver >> 16
                if ttl > 0:
                    self.subscriptions[(sid, eventgroup_id)] = True
                else:
                    self.subscriptions[(sid, eventgroup_id)] = False

            current += 16

    # Event subscription tracking
    subscriptions: Dict[Tuple[int, int], bool] = {}  # (service_id, eventgroup_id) -> acked

    def subscribe_eventgroup(self, service_id: int, instance_id: int, eventgroup_id: int, ttl: int = 0xFFFFFF):
        """Subscribe to an eventgroup from a remote service."""
        # Detect if we should use IPv6 for subscription
        use_v6 = self.interface_ip_v6 and ":" in self.interface_ip_v6
        
        # Build SubscribeEventgroup entry
        sd_payload = bytearray([0x80, 0, 0, 0])  # Flags
        sd_payload += struct.pack(">I", 16)       # Entries Len
        
        num_opts_byte = (1 << 4) | 0
        maj_ttl = (0x01 << 24) | (ttl & 0xFFFFFF)
        minor = eventgroup_id << 16
        sd_payload += struct.pack(">BBBBHHII", 0x06, 0, 0, num_opts_byte, service_id, instance_id, maj_ttl, minor)
        
        proto_id = 0x11 # UDP
        if not use_v6:
            # Options Len (12 bytes for IPv4 endpoint option: 2 len + 1 type + 1 res + 8 data = 12?)
            # Wait. If Length=9, then Type included? No, PRS_SOMEIPSD_00024 says excluding Type.
            # So Option = [Len:2][Type:1][Res:1][Data:9] = 13 bytes?
            # Wait. SOMEIP-SD Options are 4-byte aligned usually?
            # Let's check someipy again. 
            # someipy uses LENGTH = 9. 
            # someipy options_len += 12. 
            # If options_len += 12, then total bytes for one option is 12.
            # If total bytes is 12, and Length = 9. 
            # 12 - 9 = 3. This matches: 2 (Length field) + 1 (Type field) = 3.
            # So [Len:2] (value 9) + [Type:1] (value 0x04) + [Res:1] + [Data:8] = 12 bytes.
            # Yes! 9 = 1 (Res) + 4 (IP) + 1 (Res) + 1 (Proto) + 2 (Port).
            # So 9 is correct for IPv4 Endpoint.
            # And total option size is 12 bytes.
            
            sd_payload += struct.pack(">I", 12)
            sd_payload += struct.pack(">HBB", 10, 0x04, 0) # Length=10, Type=0x04
            sd_payload += socket.inet_aton(self.interface_ip)
            sd_payload += struct.pack(">BBH", 0, proto_id, self.port)
        else:
            # Options Len (24 bytes for IPv6 endpoint option: 2 len + 1 type + 21 data = 24)
            sd_payload += struct.pack(">I", 24)
            sd_payload += struct.pack(">HBB", 22, 0x06, 0) # Length=22, Type=0x06
            sd_payload += socket.inet_pton(socket.AF_INET6, self.interface_ip_v6)
            sd_payload += struct.pack(">BBH", 0, proto_id, self.port)
        
        payload_len = len(sd_payload) + 8
        someip_header = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, payload_len, 0, 1, 1, 1, 2, 0)
        
        if use_v6 and self.sd_multicast_ip_v6:
            self.sd_sock_v6.sendto(someip_header + sd_payload, (self.sd_multicast_ip_v6, self.sd_pub_port))
        elif not use_v6 and self.sd_multicast_ip:
            self.sd_sock.sendto(someip_header + sd_payload, (self.sd_multicast_ip, self.sd_pub_port))
        else:
            self.logger.log(LogLevel.ERR, "SD", "Cannot send SubscribeEventgroup: Relevant SD Multicast IP not configured.")
        
        self.subscriptions[(service_id, eventgroup_id)] = False
        self.logger.log(LogLevel.DEBUG, "SD", f"Sent SubscribeEventgroup for 0x{service_id:04x}:{eventgroup_id}")

    def unsubscribe_eventgroup(self, service_id: int, instance_id: int, eventgroup_id: int):
        """Unsubscribe from an eventgroup (TTL=0)."""
        self.subscribe_eventgroup(service_id, instance_id, eventgroup_id, ttl=0)
        self.subscriptions.pop((service_id, eventgroup_id), None)

    def is_subscription_acked(self, service_id: int, eventgroup_id: int) -> bool:
        """Check if subscription was acknowledged."""
        return self.subscriptions.get((service_id, eventgroup_id), False)

    def _send_offer(self, service_id, instance_id, major, minor, port, 
                    endpoint_ip=None, endpoint_ip_v6=None,
                    multicast_ip=None, multicast_port=None):
        if endpoint_ip is None: endpoint_ip = self.interface_ip
        if endpoint_ip_v6 is None: endpoint_ip_v6 = self.interface_ip_v6

        def is_v4(ip):
            try: return ipaddress.ip_address(ip).version == 4
            except: return False
        def is_v6(ip):
            try: return ipaddress.ip_address(ip).version == 6
            except: return False

        # Build IPv4 Offer
        if is_v4(endpoint_ip):
            sd_payload_v4 = bytearray([0x80, 0, 0, 0]) 
            sd_payload_v4 += struct.pack(">I", 16)     
            
            num_opts_v4 = 1
            if multicast_ip and is_v4(multicast_ip):
                num_opts_v4 += 1
                
            num_opts_byte = (num_opts_v4 << 4) | 0
            maj_ttl = (major << 24) | 0xFFFFFF
            sd_payload_v4 += struct.pack(">BBBBHHII", 0x01, 0, 0, num_opts_byte, service_id, instance_id, maj_ttl, minor)
            
            # Options
            options_v4 = bytearray()
            ip_int = struct.unpack(">I", socket.inet_aton(endpoint_ip))[0]
            proto_id = 0x06 if self.protocol == 'tcp' else 0x11
            # Length=10 (0x0A) for IPv4 Endpoint
            options_v4 += struct.pack(">HBBI BBH", 10, 0x04, 0, ip_int, 0, proto_id, port)
            
            if multicast_ip and is_v4(multicast_ip):
                m_ip_int = struct.unpack(">I", socket.inet_aton(multicast_ip))[0]
                # Length=10 (0x0A) for IPv4 Multicast
                options_v4 += struct.pack(">HBBI BBH", 10, 0x14, 0, m_ip_int, 0, 0x11, multicast_port or port)
                
            sd_payload_v4 += struct.pack(">I", len(options_v4))
            sd_payload_v4 += options_v4
            
            payload_len_v4 = len(sd_payload_v4) + 8
            header_v4 = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, payload_len_v4, 0, 1, 1, 1, 2, 0)
            try:
                self.sd_sock.sendto(header_v4 + sd_payload_v4, (self.sd_multicast_ip, self.sd_pub_port))
            except OSError as e:
                self.logger.log(LogLevel.WARN, "SD", f"v4 Offer send failed: {e}")

        # Build IPv6 Offer
        if is_v6(endpoint_ip_v6):
            sd_payload_v6 = bytearray([0x80, 0, 0, 0])
            sd_payload_v6 += struct.pack(">I", 16)
            
            num_opts_v6 = 1
            if multicast_ip and is_v6(multicast_ip):
                num_opts_v6 += 1
                
            num_opts_byte_v6 = (num_opts_v6 << 4) | 0
            maj_ttl = (major << 24) | 0xFFFFFF # Fixed: missing maj_ttl in original v6 block partially
            sd_payload_v6 += struct.pack(">BBBBHHII", 0x01, 0, 0, num_opts_byte_v6, service_id, instance_id, maj_ttl, minor)
            
            options_v6 = bytearray()
            # Length=22 (0x16) for IPv6 Endpoint
            options_v6 += struct.pack(">HBB", 22, 0x06, 0)
            options_v6 += socket.inet_pton(socket.AF_INET6, endpoint_ip_v6)
            proto_id = 0x06 if self.protocol == 'tcp' else 0x11
            options_v6 += struct.pack(">BBH", 0, proto_id, port)
            
            if multicast_ip and is_v6(multicast_ip):
                # Length=22 (0x16) for IPv6 Multicast
                options_v6 += struct.pack(">HBB", 22, 0x16, 0)
                options_v6 += socket.inet_pton(socket.AF_INET6, multicast_ip)
                options_v6 += struct.pack(">BBH", 0, 0x11, multicast_port or port)
                
            sd_payload_v6 += struct.pack(">I", len(options_v6))
            sd_payload_v6 += options_v6

            payload_len_v6 = len(sd_payload_v6) + 8
            header_v6 = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, payload_len_v6, 0, 1, 1, 1, 2, 0)
            try:
                if self.sd_multicast_ip_v6:
                    self.sd_sock_v6.sendto(header_v6 + sd_payload_v6, (self.sd_multicast_ip_v6, self.sd_pub_port))
            except OSError as e:
                # Log and continue - Windows loopback sometimes fails for v6 multicast
                self.logger.log(LogLevel.DEBUG, "SD", f"v6 Offer send failed (expected on some Windows configs): {e}")
        
        # Sent Dual-Stack Offer log is already below the stacked blocks
        self.logger.log(LogLevel.DEBUG, "SD", f"Sent Dual-Stack Offer for 0x{service_id:04x} [{endpoint_ip}, {endpoint_ip_v6}]")

    def send_request(self, service_id, method_id, payload, target_addr, msg_type=0, wait_for_response=False, timeout=2.0):
        # Generate Session ID
        session_id = self.session_manager.next_session_id(service_id, method_id)
        
        # SOME/IP Header: [SvcId:2][MethId:2][Len:4][ClientId:2][SessionId:2][Proto:1][Iface:1][MsgType:1][Ret:1]
        header = struct.pack(">HHIHH4B", service_id, method_id, len(payload)+8, 0, session_id, 1, 1, msg_type, 0)
        
        event = None
        if wait_for_response:
            event = threading.Event()
            self.pending_requests[(service_id, method_id, session_id)] = event
            
        # Determine protocol
        proto = self.protocol
        if len(target_addr) > 2:
            proto = target_addr[2]
            target_addr = (target_addr[0], target_addr[1])

        if proto == "tcp":
            try:
                # Detect family
                family = socket.AF_INET6 if ":" in target_addr[0] else socket.AF_INET
                with socket.socket(family, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    s.connect(target_addr)
                    s.sendall(header + payload)
                    if wait_for_response:
                        data = s.recv(4096)
                        if len(data) >= 16:
                            self.request_results[(service_id, method_id, session_id)] = data[16:]
                            return self.request_results.pop((service_id, method_id, session_id))
            except Exception as e:
                self.logger.log(LogLevel.ERROR, "Runtime", f"TCP Send failed: {e}")
                return None
        else:
            if ":" in target_addr[0]:
                self.sock_v6.sendto(header + payload, target_addr)
            else:
                self.sock.sendto(header + payload, target_addr)
        
        if wait_for_response and event:
            if event.wait(timeout):
                return self.request_results.pop((service_id, method_id, session_id), None)
            else:
                self.pending_requests.pop((service_id, method_id, session_id), None)
                self.logger.log(LogLevel.WARN, "Runtime", f"Timeout waiting for response to 0x{service_id:04x}:0x{method_id:04x}")
                return None
        return None


    def _run(self):
        while self.running:
            # Periodic SD Offers
            now = time.time()
            if now - self.last_offer_time > self.offer_interval:
                self.last_offer_time = now
                for (sid, iid, major, minor, port, ep_ip, ep_ip_v6, m_ip, m_port) in self.offered_services:
                    self._send_offer(sid, iid, major, minor, port, ep_ip, ep_ip_v6, m_ip, m_port)

            inputs = [self.sock, self.sock_v6, self.sd_sock, self.sd_sock_v6]
            if self.tcp_listener:
                inputs.append(self.tcp_listener)
            if self.tcp_listener_v6:
                inputs.append(self.tcp_listener_v6)
            for client_sock, _ in self.tcp_clients:
                inputs.append(client_sock)

            readable, _, _ = select.select(inputs, [], [], 0.1)
            for s in readable:
                if s in (self.tcp_listener, self.tcp_listener_v6):
                    client_sock, addr = s.accept()
                    client_sock.setblocking(False)
                    self.tcp_clients.append((client_sock, addr))
                    self.logger.log(LogLevel.INFO, "Runtime", f"Accepted TCP connection from {addr}")
                    continue

                try:
                    if s in (self.sock, self.sock_v6, self.sd_sock, self.sd_sock_v6):
                        data, addr = s.recvfrom(1500)
                    else:
                        data = s.recv(1500)
                        addr = next(a for cs, a in self.tcp_clients if cs == s)
                except (ConnectionResetError, ConnectionAbortedError):
                    if s not in (self.sock, self.sock_v6, self.sd_sock, self.sd_sock_v6):
                        self.tcp_clients = [(cs, a) for cs, a in self.tcp_clients if cs != s]
                        s.close()
                    continue
                except Exception as e:
                    self.logger.log(LogLevel.ERROR, "Runtime", f"Error in event loop: {e}")
                    continue

                if not data:
                    if s not in (self.sock, self.sock_v6, self.sd_sock, self.sd_sock_v6):
                        self.tcp_clients = [(cs, a) for cs, a in self.tcp_clients if cs != s]
                        s.close()
                    continue

                if s in (self.sock, self.sock_v6) or s in [cs for cs, a in self.tcp_clients]:
                    if len(data) >= 16:
                        sid, mid, length, cid, ssid, pv, iv, mt, rc = struct.unpack(">HHIHH4B", data[:16])
                        if mt in (0x00, 0x01) and sid in self.services:
                            res_payload = self.services[sid].handle({'method_id': mid}, data[16:length+8])
                            if res_payload:
                                res_header = struct.pack(">HHIHH4B", sid, mid, len(res_payload)+8, cid, ssid, pv, iv, 0x80, 0)
                                if s in (self.sock, self.sock_v6):
                                    s.sendto(res_header + res_payload, addr)
                                else:
                                    s.sendall(res_header + res_payload)
                    if len(data) >= 16: # This check is redundant if the previous one passed, but kept for structural consistency with the request
                        sid, mid, length, cid, ssid, pv, iv, mt, rc = struct.unpack(">HHIHH4B", data[:16])
                        if mt == 0x80: # RESPONSE
                            key = (sid, mid, ssid)
                            if key in self.pending_requests:
                                self.request_results[key] = data[16:length+8]
                                self.pending_requests.pop(key).set()
                elif s in (self.sd_sock, self.sd_sock_v6):
                    if len(data) >= 16:
                        self.logger.log(LogLevel.DEBUG, "SD", f"Packet from {addr} len={len(data)}")
                        self._handle_sd_packet(data, addr)
