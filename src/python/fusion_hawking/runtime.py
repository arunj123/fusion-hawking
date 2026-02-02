import socket
import struct
import threading
import time
import select
from typing import Dict, Tuple, Optional
from .logger import LogLevel, ConsoleLogger, ILogger

class RequestHandler:
    def get_service_id(self) -> int:
        raise NotImplementedError()
    def handle(self, header: Dict, payload: bytes) -> bytes:
        raise NotImplementedError()

import json
import os

class SomeIpRuntime:
    def __init__(self, config_path: str, instance_name: str, logger: Optional[ILogger] = None):
        self.logger = logger or ConsoleLogger()
        self.services: Dict[int, RequestHandler] = {}
        self.offered_services = [] # list of (sid, iid, port)
        self.remote_services: Dict[int, Tuple[str, int]] = {}
        self.running = False
        self.last_offer_time = 0
        
        self.config = self._load_config(config_path, instance_name)
        
        # Determine Bind Port
        bind_port = 0
        if self.config and 'providing' in self.config:
            vals = list(self.config['providing'].values())
            if vals and 'port' in vals[0]:
                bind_port = vals[0]['port']

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(('0.0.0.0', bind_port))
        except Exception:
            self.logger.log(LogLevel.WARN, "Runtime", f"Failed to bind {bind_port}, using ephemeral")
            self.sock.bind(('0.0.0.0', 0))
            
        self.port = self.sock.getsockname()[1]
        self.logger.log(LogLevel.INFO, "Runtime", f"Initialized '{instance_name}' on port {self.port}")
        
        # SD Socket
        self.sd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sd_sock.bind(('0.0.0.0', 30490))
        mreq = struct.pack("4sl", socket.inet_aton("224.0.0.1"), socket.INADDR_ANY)
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        self.sock.setblocking(False)
        self.sd_sock.setblocking(False)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        # Wake up select
        try:
            ws = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ws.sendto(b'', ('127.0.0.1', self.port))
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
                return data['instances'].get(name, {})
        except:
            return {}

    def offer_service(self, alias: str, handler: RequestHandler):
        sid = handler.get_service_id()
        self.services[sid] = handler
        # Resolve from config if possible
        instance_id = 1
        port = self.port
        if self.config and 'providing' in self.config:
            cfg = self.config['providing'].get(alias)
            if cfg:
                sid = cfg.get('service_id', sid)
                instance_id = cfg.get('instance_id', 1)
                port = cfg.get('port', self.port)
        
        self.offered_services.append((sid, instance_id, port))
        self._send_offer(sid, instance_id, port)
        self.logger.log(LogLevel.INFO, "Runtime", f"Offered {alias} (0x{sid:04x}) on port {port}")

    def get_client(self, alias: str, client_cls, timeout: float = 5.0):
        """Get a client for a remote service, waiting for SD discovery if needed."""
        # Resolve service ID from config
        service_id = client_cls.SERVICE_ID if hasattr(client_cls, 'SERVICE_ID') else 0
        if self.config and 'required' in self.config:
            req_cfg = self.config['required'].get(alias)
            if req_cfg:
                service_id = req_cfg.get('service_id', service_id)
        
        # Wait for service discovery
        endpoint = self._wait_for_service(service_id, alias, timeout)
        if endpoint:
            return client_cls(self, alias)
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
                self.logger.log(LogLevel.INFO, "Runtime", f"Discovered '{alias}' (0x{service_id:04x}) at {endpoint[0]}:{endpoint[1]}")
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
                self._handle_sd_packet(data)
            except Exception:
                pass

    def _handle_sd_packet(self, data: bytes):
        """Parse and handle an SD packet."""
        if len(data) >= 56:
            sid = struct.unpack(">H", data[28:30])[0]
            ip_bytes = data[48:52]
            ip_str = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
            port = struct.unpack(">H", data[54:56])[0]
            if ip_str != '0.0.0.0' and port > 0:
                self.remote_services[sid] = (ip_str, port)
                self.logger.log(LogLevel.DEBUG, "SD", f"Discovered 0x{sid:04x} at {ip_str}:{port}")

    # Event subscription tracking
    subscriptions: Dict[Tuple[int, int], bool] = {}  # (service_id, eventgroup_id) -> acked

    def subscribe_eventgroup(self, service_id: int, instance_id: int, eventgroup_id: int, ttl: int = 0xFFFFFF):
        """Subscribe to an eventgroup from a remote service."""
        # Build SubscribeEventgroup entry
        sd_payload = bytearray([0x80, 0, 0, 0])  # Flags
        sd_payload += struct.pack(">I", 16)       # Entries Len (16 bytes = 1 entry)
        
        # Entry: Type=0x06 (SubscribeEventgroup), with our endpoint option
        num_opts_byte = (1 << 4) | 0
        maj_ttl = (0x01 << 24) | (ttl & 0xFFFFFF)
        minor = eventgroup_id << 16  # eventgroup_id in upper 16 bits
        sd_payload += struct.pack(">BBBBHHII", 0x06, 0, 0, num_opts_byte, service_id, instance_id, maj_ttl, minor)
        
        # Options Len (12 bytes for IPv4 endpoint option)
        sd_payload += struct.pack(">I", 12)
        
        # Option IPv4 endpoint (our address for receiving events)
        sd_payload += struct.pack(">HBB", 9, 0x04, 0)  # Len=9, Type=IPv4, Res
        sd_payload += struct.pack(">I", 0x7F000001)    # 127.0.0.1
        sd_payload += struct.pack(">BBH", 0, 0x11, self.port)  # Res, UDP, Port
        
        payload_len = len(sd_payload) + 8
        someip_header = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, payload_len, 0, 1, 1, 1, 2, 0)
        self.sd_sock.sendto(someip_header + sd_payload, ("224.0.0.1", 30490))
        
        self.subscriptions[(service_id, eventgroup_id)] = False
        self.logger.log(LogLevel.DEBUG, "SD", f"Sent SubscribeEventgroup for 0x{service_id:04x}:{eventgroup_id}")

    def unsubscribe_eventgroup(self, service_id: int, instance_id: int, eventgroup_id: int):
        """Unsubscribe from an eventgroup (TTL=0)."""
        self.subscribe_eventgroup(service_id, instance_id, eventgroup_id, ttl=0)
        self.subscriptions.pop((service_id, eventgroup_id), None)

    def is_subscription_acked(self, service_id: int, eventgroup_id: int) -> bool:
        """Check if subscription was acknowledged."""
        return self.subscriptions.get((service_id, eventgroup_id), False)

    def _send_offer(self, service_id, instance_id, port):
        # SD Payload Construction (Match C++ logic)
        sd_payload = bytearray([0x80, 0, 0, 0]) # Flags
        sd_payload += struct.pack(">I", 16)     # Entries Len (4 bytes)
        
        # Entry (16 bytes)
        # Type(1), Idx1(1), Idx2(1), NumOpts(1), SvcId(2), InstId(2), Maj/TTL(4), Min(4)
        num_opts_byte = (1 << 4) | 0
        maj_ttl = (1 << 24) | 0xFFFFFF
        sd_payload += struct.pack(">BBBBHHII", 0x01, 0, 0, num_opts_byte, service_id, instance_id, maj_ttl, 10)
        
        # Options Len (4 bytes)
        sd_payload += struct.pack(">I", 9)
        
        # Option IPv4 (9 bytes)
        # Len(2), Type(1), Res(1), IP(4), Res(1), Proto(1), Port(2)
        sd_payload += struct.pack(">HBBI BBH", 9, 0x04, 0, 0x7F000001, 0, 0x11, port)
        
        payload_len = len(sd_payload) + 8
        someip_header = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, payload_len, 0, 1, 1, 1, 2, 0)
        self.sd_sock.sendto(someip_header + sd_payload, ("224.0.0.1", 30490))
        self.logger.log(LogLevel.DEBUG, "SD", f"Sent Offer for 0x{service_id:04x}")

    def send_request(self, service_id, method_id, payload, target_addr, msg_type=0):
        # SOME/IP Header: [SvcId:2][MethId:2][Len:4][ClientId:2][SessionId:2][Proto:1][Iface:1][MsgType:1][Ret:1]
        header = struct.pack(">HHIHH4B", service_id, method_id, len(payload)+8, 0, 1, 1, 1, msg_type, 0)
        self.sock.sendto(header + payload, target_addr)

    def _run(self):
        while self.running:
            # Periodic SD Offers
            now = time.time()
            if now - self.last_offer_time > 0.5:  # Faster offer interval for quicker discovery
                self.last_offer_time = now
                for (sid, iid, port) in self.offered_services:
                    self._send_offer(sid, iid, port)

            readable, _, _ = select.select([self.sock, self.sd_sock], [], [], 0.5)
            for s in readable:
                data, addr = s.recvfrom(1500)
                if s == self.sock:
                    if len(data) >= 16:
                        sid, mid, length, cid, ssid, pv, iv, mt, rc = struct.unpack(">HHIHH4B", data[:16])
                        # Only handle Requests (0x00) or Requests No Return (0x01)
                        if mt in (0x00, 0x01) and sid in self.services:
                            res_payload = self.services[sid].handle({'method_id': mid}, data[16:])
                            if res_payload:
                                res_header = struct.pack(">HHIHH4B", sid, mid, len(res_payload)+8, cid, ssid, pv, iv, 0x80, 0)
                                self.sock.sendto(res_header + res_payload, addr)
                elif s == self.sd_sock:
                    # Parse SD
                    if len(data) >= 56:
                        sid = struct.unpack(">H", data[28:30])[0]
                        ip_bytes = data[48:52]
                        ip_str = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
                        port = struct.unpack(">H", data[54:56])[0]
                        if ip_str != '0.0.0.0' and port > 0:
                            self.remote_services[sid] = (ip_str, port)
                            self.logger.log(LogLevel.DEBUG, "SD", f"Discovered 0x{sid:04x} at {ip_str}:{port}")
