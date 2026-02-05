import socket
import struct
import threading
import time
import select
from typing import Dict, Tuple, Optional
from enum import IntEnum
from .logger import LogLevel, ConsoleLogger, ILogger


class MessageType(IntEnum):
    """SOME/IP Message Types as defined in AUTOSAR spec"""
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
    """SOME/IP Return Codes as defined in AUTOSAR spec"""
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
        self.thread = None
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
        # Get interface IP from config (mandatory)
        interface_ip = self.config.get('ip', '127.0.0.1') if self.config else '127.0.0.1'
        # Join Multicast on configured interface
        self.interface_ip = interface_ip
        mreq = struct.pack("4s4s", socket.inet_aton("224.0.0.1"), socket.inet_aton(self.interface_ip))
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        # Ensure outgoing multicast uses configured interface
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.interface_ip))
        # Enable Multicast Loopback
        self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        
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
            ttl = struct.unpack(">I", data[current+8:current+12])[0]
            ttl = ttl & 0xFFFFFF # Mask Major Version
            min_ver = struct.unpack(">I", data[current+12:current+16])[0]
            
            # Options Handling (Simplified: Scan all options after entries)
            options_start = entries_end + 4 # Skip Options Len
            
            if entry_type == 0x01: # OfferService
                # Find Endpoint Option (assuming standard layout with 1 option)
                # In this simplified parser, we scan options for IPv4Endpoint
                # Ideally, we look at indices.
                # Assuming simple 1-1 mapping for demo/test compatibility.
                # Or just scan *all* options for now because Python Demo is Client-only mostly.
                
                # Robust way: parse options into list
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
                                parsed_opts.append( (ip_str, p) )
                            else:
                                parsed_opts.append(None)
                            opt_ptr += 2 + l # Length field is 2 bytes, then 'l' bytes of content
                    except: pass
                    
                if ttl > 0:
                    # Resolve endpoint
                    endpoint = None
                    if num_opts_1 > 0 and index1 < len(parsed_opts):
                        endpoint = parsed_opts[index1]
                    
                    if endpoint and endpoint[0] != '0.0.0.0':
                        self.remote_services[sid] = endpoint
                        self.logger.log(LogLevel.DEBUG, "SD", f"Discovered 0x{sid:04x} at {endpoint[0]}:{endpoint[1]}")
                        
            elif entry_type == 0x06: # SubscribeEventgroup
                # Verify if we provide this service? 
                # For test Mock server, we want to ACK.
                # We check `self.offered_services`
                
                base_endpoint = None
                 # Parse options same as above
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
                                parsed_opts.append( (ip_str, p) )
                            else:
                                parsed_opts.append(None)
                            opt_ptr += 3 + l
                    except: pass

                if num_opts_1 > 0 and index1 < len(parsed_opts):
                    base_endpoint = parsed_opts[index1]

                is_offered = any(s[0] == sid for s in self.offered_services)
                
                if is_offered and ttl > 0 and base_endpoint:
                     # Send ACK
                     # Simplified ACK Packet
                     eventgroup_id = min_ver >> 16
                     ack_payload = bytearray([0x80, 0, 0, 0])
                     ack_payload += struct.pack(">I", 16)
                     # Entry: Type 0x07 (Ack)
                     ack_payload += struct.pack(">BBBBHHII", 0x07, 0, 0, 0, sid, iid, ttl | (1<<24), min_ver)
                     ack_payload += struct.pack(">I", 0) # 0 Options
                     
                     plen = len(ack_payload) + 8
                     sh = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, plen, 0, 1, 1, 1, 2, 0)
                     
                     # Send to Multicast (or Unicast if we implemented it properly)
                     self.sd_sock.sendto(sh + ack_payload, ("224.0.0.1", 30490))
                    
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
        sd_payload += struct.pack(">I", struct.unpack(">I", socket.inet_aton(self.interface_ip))[0])
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
        sd_payload += struct.pack(">I", 12)
        
        # Option IPv4 (9 bytes)
        # Len(2), Type(1), Res(1), IP(4), Res(1), Proto(1), Port(2)
        ip_int = struct.unpack(">I", socket.inet_aton(self.interface_ip))[0]
        sd_payload += struct.pack(">HBBI BBH", 9, 0x04, 0, ip_int, 0, 0x11, port)
        
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
                try:
                    data, addr = s.recvfrom(1500)
                except ConnectionResetError:
                    # Windows UDP Quirks: Host Unreachable from previous send closes socket on recv
                    continue
                except Exception:
                    continue

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
