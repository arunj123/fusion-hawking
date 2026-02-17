import os
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
import collections
from typing import Dict, Tuple, Optional, Set, List
from enum import IntEnum

from .logger import LogLevel, ConsoleLogger, ILogger
from .tp import TpHeader, TpReassembler, segment_payload

class MessageType(IntEnum):
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
    E_OK = 0x00
    E_NOT_OK = 0x01
    E_UNKNOWN_SERVICE = 0x02
    E_UNKNOWN_METHOD = 0x03
    E_NOT_READY = 0x04
    E_NOT_REACHABLE = 0x05
    E_TIMEOUT = 0x06
    E_WRONG_PROTOCOL_VERSION = 0x07
    E_WRONG_INTERFACE_VERSION = 0x08
    E_MALFORMED_MESSAGE = 0x09
    E_WRONG_MESSAGE_TYPE = 0x0A
    E_E2E_REPEATED = 0x0B
    E_E2E_WRONG_SEQUENCE = 0x0C
    E_E2E_NOT_AVAILABLE = 0x0D
    E_E2E_NO_NEW_DATA = 0x0E

class SessionIdManager:
    def __init__(self):
        self._counters: Dict[Tuple[int, int], int] = {}
    def next_session_id(self, service_id: int, method_id: int) -> int:
        key = (service_id, method_id)
        current = self._counters.get(key, 1)
        self._counters[key] = (current % 0xFFFF) + 1
        return current

    def reset(self, service_id: int, method_id: int):
        self._counters.pop((service_id, method_id), None)

    def reset_all(self):
        self._counters.clear()

class RequestHandler:
    def get_service_id(self) -> int: raise NotImplementedError()
    def get_major_version(self) -> int: return 1
    def get_minor_version(self) -> int: return 0
    def handle(self, header: Dict, payload: bytes) -> bytes: raise NotImplementedError()

class SomeIpRuntime:
    def __init__(self, config_path: str, instance_name: str, logger: Optional[ILogger] = None):
        self.logger = logger or ConsoleLogger()
        self.services: Dict[int, RequestHandler] = {}
        self.offered_services = [] # (sid, iid, major, minor, ip, port, proto, iface_alias)
        self.remote_services: Dict[Tuple[int, int], Tuple[str, int, str]] = {}
        self.running = False
        self.thread = None
        self.last_offer_time = 0
        self.offer_interval = 2.0
        self.packet_dump = os.environ.get("FUSION_PACKET_DUMP") == "1"
        
        self.interfaces: Dict[str, Dict] = {}
        self.sd_listeners: Dict[str, socket.socket] = {}
        self.listeners: Dict[Tuple[str, int, str], socket.socket] = {}
        self.listeners_by_name: Dict[str, socket.socket] = {}
        self.endpoint_routing: Dict[Tuple[str, int, str], Set[int]] = collections.defaultdict(set)
        
        self.pending_requests: Dict[Tuple[int, int, int], threading.Event] = {}
        self.request_results: Dict[Tuple[int, int, int], bytes] = {}
        self.session_manager = SessionIdManager()
        self.tcp_clients: List[Tuple[socket.socket, Tuple]] = []
        self.subscriptions: Dict[Tuple[int, int], bool] = {}
        
        self.tp_reassembler = TpReassembler()

        self.config, self.interfaces, self.endpoints = self._load_config(config_path, instance_name)
        if not self.config:
            self.logger.log(LogLevel.ERROR, "Runtime", f"Instance '{instance_name}' not found.")
            return

        self._setup_sd()
        self._setup_transports()

    def _load_config(self, path, name):
        try:
            with open(path, 'r') as f: data = json.load(f)
            inst = data.get('instances', {}).get(name, {})
            ifaces = data.get('interfaces', {})
            eps = data.get('endpoints', {})
            if not inst:
                print(f"ERROR: Instance '{name}' not found in {path}. Keys: {list(data.get('instances', {}).keys())}")
            return inst, ifaces, eps
        except Exception as e:
            print(f"ERROR: Failed to load config from {path}: {e}")
            return {}, {}, {}

    def _setup_sd(self):
        for alias, iface in self.interfaces.items():
            sd = iface.get("sd", {})
            if not sd: continue
            eps = iface.get("endpoints", {})
            v4_ep = sd.get("endpoint_v4") or sd.get("endpoint")
            if v4_ep in eps:
                ep = eps[v4_ep]
                # Try all unicast IPs on this interface until one works
                for inner in eps.values():
                    t_ip = inner["ip"]
                    if ":" not in t_ip and self._is_local_unicast(t_ip):
                        # Attempt to create socket using this IP as interface IP
                        s = self._create_sd_socket_v4(t_ip, ep["ip"], ep["port"], t_ip, iface["name"])
                        if s:
                            self.sd_listeners[f"{alias}_v4"] = s
                            break

            v6_ep = sd.get("endpoint_v6")
            if v6_ep in eps:
                ep = eps[v6_ep]
                # Find local ipv6
                iface_ip_v6 = next((inner["ip"] for inner in eps.values() if self._is_local_unicast(inner["ip"]) and ":" in inner["ip"]), None)
                if iface_ip_v6:
                    # Strict Binding: Bind to the specific interface IP
                    s = self._create_sd_socket_v6(ep["ip"], ep["port"], iface["name"], iface_ip_v6)
                    if s: self.sd_listeners[f"{alias}_v6"] = s

    def _create_sd_socket_v4(self, iface_ip, m_ip, port, bind_ip="", iface_name=""):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try: s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except: pass
            
            if platform.system() == "Linux":
                s.bind((m_ip, port))
                # Try strict binding to interface device if name provided
                if iface_name:
                    try:
                        # SO_BINDTODEVICE = 25
                        s.setsockopt(socket.SOL_SOCKET, 25, iface_name.encode('utf-8'))
                    except PermissionError:
                        self.logger.log(LogLevel.WARN, "Runtime", f"Failed to set SO_BINDTODEVICE on {iface_name} (requires root). Multicast reception might be loose.")
                    except Exception as e:
                        self.logger.log(LogLevel.WARN, "Runtime", f"Failed to set SO_BINDTODEVICE on {iface_name}: {e}")
            elif os.name == "nt":
                # Windows: Bind to wildcard to allow sharing with other processes (like someipy)
                # relying on the same behavior.
                try:
                    s.bind(("", port))
                except Exception:
                    # Fallback to interface IP if wildcard fails
                    s.bind((iface_ip, port))
            else:
                # Others: Strict binding to interface IP
                s.bind((iface_ip, port))

            print(f"DEBUG: Setting IP_ADD_MEMBERSHIP {m_ip} on {iface_ip} ({iface_name})")
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, struct.pack("4s4s", socket.inet_aton(m_ip), socket.inet_aton(iface_ip)))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            # Add SO_BROADCAST for unicast broadcast if used
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setblocking(False)
            return s
        except Exception as e:
            print(f"DEBUG: _create_sd_socket_v4 failed for {iface_ip}: {e}")
            return None

    def _create_sd_socket_v6(self, m_ip, port, iface_name, bind_ip="::"):
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try: s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except: pass
            s.bind((bind_ip, port))
            idx = self._resolve_interface_index(iface_name)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, struct.pack("16si", socket.inet_pton(socket.AF_INET6, m_ip), idx))
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, idx)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)
            s.setblocking(False)
            return s
        except: return None

    def _setup_transports(self):
        # Bind all endpoints of interfaces assigned to this instance
        iface_names = self.config.get('interfaces', [])
        if not iface_names and self.interfaces:
            # Fallback: if no interfaces list in instance, but global interfaces exist, use 'primary' or first
            iface_names = ["primary"] if "primary" in self.interfaces else [list(self.interfaces.keys())[0]]

        for alias in iface_names:
            if alias not in self.interfaces: continue
            iface_cfg = self.interfaces[alias]
            eps = iface_cfg.get("endpoints", {})
            for ep_name, ep in eps.items():
                ip, port, proto = ep["ip"], ep.get("port", 0), ep.get("protocol", "udp").lower()
                if not self._is_local_unicast(ip): continue
                key = (ip, port, proto)
                if key not in self.listeners:
                    try:
                        s = socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM)
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        try: s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                        except: pass
                        s.bind((ip, port))
                        if proto == 'tcp': s.listen(5)
                        s.setblocking(False)
                        actual_port = s.getsockname()[1]
                        self.listeners[(ip, actual_port, proto)] = s
                        self.listeners_by_name[ep_name] = s
                        self.logger.log(LogLevel.INFO, "Runtime", f"Bound {ip}:{actual_port} ({proto}) on {alias} (endpoint={ep_name})")
                    except Exception as e:
                        self.logger.log(LogLevel.WARN, "Runtime", f"Failed to bind {ip}:{port} on {alias}: {e}")
                        continue
        
        # Better: iterate providing services and find their actual bound ports
        if 'providing' in self.config:
            for name, cfg in self.config['providing'].items():
                sid, ep_name = cfg.get('service_id'), cfg.get('endpoint')
                aliases = cfg.get('interfaces', []) or iface_names
                offer_on = cfg.get('offer_on', {})
                
                for a in aliases:
                    if a not in self.interfaces: continue
                    
                    # Resolve endpoint for this interface
                    target_ep_name = offer_on.get(a) or ep_name
                    if not target_ep_name and not ep_name and not offer_on:
                         # Use first endpoint as fallback
                         eps = self.interfaces[a].get("endpoints", {})
                         if eps: target_ep_name = list(eps.keys())[0]

                    ep = self.interfaces[a].get("endpoints", {}).get(target_ep_name)
                    if not ep and target_ep_name in self.endpoints: ep = self.endpoints[target_ep_name] # Global fallback
                    
                    if not ep: continue
                    ip, proto = ep["ip"], ep.get("protocol", "udp").lower()
                    
                    # Use listeners_by_name if available for this specific endpoint
                    if target_ep_name in self.listeners_by_name:
                        s = self.listeners_by_name[target_ep_name]
                        l_ip, l_p = s.getsockname()[:2]
                        l_pr = proto
                        self.endpoint_routing[(l_ip, l_p, l_pr)].add(sid)
                        self.offered_services.append((sid, cfg.get('instance_id', 1), cfg.get('major_version', 1), cfg.get('minor_version', 0), l_ip, l_p, l_pr, a))
                        print(f"DEBUG: Offered service {sid} on {l_ip}:{l_p} {l_pr} (from {target_ep_name})")
                        continue

                    ip, proto = ep["ip"], ep.get("protocol", "udp").lower()
                    # Find the listener that was bound for this (ip, proto, alias)
                    # Since we might have bound port 0, we match on ip/proto
                    for (l_ip, l_p, l_pr), s in self.listeners.items():
                        if l_ip == ip and l_pr == proto:
                            self.endpoint_routing[(l_ip, l_p, l_pr)].add(sid)
                            self.offered_services.append((sid, cfg.get('instance_id', 1), cfg.get('major_version', 1), cfg.get('minor_version', 0), l_ip, l_p, l_pr, a))
                            break

    def _resolve_interface_index(self, name):
        if not name: return 0
        try: return socket.if_nametoindex(name)
        except: pass
        if platform.system() == "Windows":
            try:
                res = subprocess.run(["netsh", "interface", "ipv4", "show", "interfaces"], capture_output=True, text=True)
                for line in res.stdout.splitlines():
                    if name in line:
                        m = re.search(r"^\s*(\d+)", line)
                        if m: return int(m.group(1))
            except: pass
        return 0

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread: self.thread.join(timeout=1.0)
        
        # Close listeners
        for s in list(self.listeners.values()) + list(self.sd_listeners.values()):
            try: s.close()
            except: pass
            
        # Close TCP clients
        for c, _ in self.tcp_clients:
            try: c.close()
            except: pass
        self.tcp_clients.clear()

        # Cancel pending requests
        for req_id, event in self.pending_requests.items():
            event.set() # Wake up waiting threads
        self.pending_requests.clear()

    def offer_service(self, alias, handler):
        if 'providing' not in self.config or alias not in self.config['providing']: return
        self.services[handler.get_service_id()] = handler
        self.logger.log(LogLevel.INFO, "Runtime", f"Service '{alias}' registered.")

    def get_client(self, name, client_cls, timeout=5.0):
        if 'required' not in self.config or name not in self.config['required']: return None
        cfg = self.config['required'][name]
        sid, major = cfg.get('service_id'), cfg.get('major_version', 1)
        # Static
        ep_name = cfg.get('endpoint')
        if ep_name and ep_name in self.endpoints:
            ep = self.endpoints[ep_name]
            self.remote_services[(sid, major)] = (ep["ip"], ep["port"], ep.get("protocol", "udp").lower())
            return client_cls(self, name) if client_cls else True
        # Wait SD
        if self.wait_for_service(sid, cfg.get('instance_id', 0xFFFF), major, timeout):
            return client_cls(self, name) if client_cls else True
        return None

    def wait_for_service(self, service_id, instance_id, major_version=1, timeout=5.0):
        """
        Waits for a service to be available.
        """
        start = time.time()
        while time.time() - start < timeout:
             if (service_id, major_version) in self.remote_services:
                 return True
             time.sleep(0.1)
        return False

    def subscribe_eventgroup(self, service_id: int, instance_id: int, eventgroup_id: int, ttl: int = 3):
        key = (service_id, eventgroup_id)
        self.subscriptions[key] = True
        self.logger.log(LogLevel.INFO, "Runtime", f"Subscribed to {service_id:x}:{eventgroup_id:x} (instance={instance_id}, ttl={ttl})")
        
        # Send SD Subscribe packet
        # We need to look up which interface to send this on.
        # For now, we broadcast on all SD enabled interfaces or use a specific one if configured?
        # The subscription usually goes to the interface where the service was found or all.
        # Simple approach: Send on all SD interfaces.
        for alias in self.sd_listeners.keys():
             # alias is like "eth0_v4" or "eth0_v6"
             real_alias = alias.rsplit("_", 1)[0]
             is_v6 = "_v6" in alias
             self._send_subscribe(service_id, instance_id, eventgroup_id, ttl, real_alias, is_v6)

    def unsubscribe_eventgroup(self, service_id: int, instance_id: int, eventgroup_id: int):
        key = (service_id, eventgroup_id)
        if key in self.subscriptions:
            del self.subscriptions[key]
            self.logger.log(LogLevel.INFO, "Runtime", f"Unsubscribed from {service_id:x}:{eventgroup_id:x}")


    def send_request(self, sid, mid, payload, target_addr, msg_type=0, wait_for_response=False, timeout=2.0):
        ssid = self.session_manager.next_session_id(sid, mid)
        event = threading.Event() if wait_for_response else None
        if event: self.pending_requests[(sid, mid, ssid)] = event
        
        ip, p, proto = target_addr[0], target_addr[1], (target_addr[2] if len(target_addr) > 2 else "udp")
        
        MAX_SEG_PAYLOAD = 1392
        
        try:
            sock = None
            if proto == "tcp":
                 # TCP logic unchanged
                with socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout); s.connect((ip, p))
                    header = struct.pack(">HHIHH4B", sid, mid, len(payload)+8, 0, ssid, 1, 1, msg_type, 0)
                    s.sendall(header + payload)
                    if wait_for_response:
                        d = s.recv(4096)
                        if len(d) >= 16: 
                             self.request_results[(sid, mid, ssid)] = d[16:]
                             return d[16:] # Optimization: return directly if TCP sync
            else:
                sock = next((s for (il, pl, prl), s in self.listeners.items() if prl == "udp" and ((":" in ip) == (":" in il))), None)
                if not sock:
                    sock = socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

                if len(payload) > MAX_SEG_PAYLOAD:
                    # Segment Request
                    segments = segment_payload(payload, MAX_SEG_PAYLOAD)
                    base_mt = msg_type | 0x20 # Add TP flag (e.g. 0x00 -> 0x20)
                    
                    for tp_h, chunk in segments:
                        final_pld = tp_h.serialize() + chunk
                        h = struct.pack(">HHIHH4B", sid, mid, len(final_pld)+8, 0, ssid, 1, 1, base_mt, 0)
                        sock.sendto(h + final_pld, (ip, p))
                        # Small delay to prevent packet loss on UDP loopback in some envs
                        if len(segments) > 10: time.sleep(0.001) 
                else:
                    # Normal
                    header = struct.pack(">HHIHH4B", sid, mid, len(payload)+8, 0, ssid, 1, 1, msg_type, 0)
                    sock.sendto(header + payload, (ip, p))
                    
        except Exception as e:
            print(f"DEBUG: send_request failed to {ip}:{p} - {e}")
            if event: self.pending_requests.pop((sid, mid, ssid), None)
            return None
            
        if event and event.wait(timeout): return self.request_results.pop((sid, mid, ssid), None)
        return None

    def _run(self):
        while self.running:
            if time.time() - self.last_offer_time > self.offer_interval:
                self.last_offer_time = time.time()
                for (sid, iid, maj, min, ip, p, pr, a) in self.offered_services: self._send_offer(sid, iid, maj, min, p, ip, pr, a)
            inputs = list(self.listeners.values()) + list(self.sd_listeners.values()) + [c for c, a in self.tcp_clients]
            sock_to_sd = {v: k for k, v in self.sd_listeners.items()}
            try: r, _, _ = select.select(inputs, [], [], 0.1)
            except: continue
            for s in r:
                if s in self.listeners.values() and s.type == socket.SOCK_STREAM:
                    try: c, a = s.accept(); c.setblocking(False); self.tcp_clients.append((c, a))
                    except: pass
                else:
                    try:
                        if s.type == socket.SOCK_DGRAM: d, a = s.recvfrom(4096)
                        else: d, a = s.recv(4096), next((addr for c, addr in self.tcp_clients if c == s), ("?", 0))
                    except:
                        if s.type == socket.SOCK_STREAM: self.tcp_clients = [(c, a) for c, a in self.tcp_clients if c != s]; s.close()
                        continue
                    if not d:
                        if s.type == socket.SOCK_STREAM: self.tcp_clients = [(c, a) for c, a in self.tcp_clients if c != s]; s.close()
                        continue
                    if s in self.sd_listeners.values():
                        if self.packet_dump: self._dump_packet(d, a)
                        self._handle_sd_packet(d, a, sock_to_sd[s].rsplit("_", 1)[0])
                    elif len(d) >= 16:
                        if self.packet_dump: self._dump_packet(d, a)
                        sid, mid, length, cid, ssid, pv, iv, mt, rc = struct.unpack(">HHIHH4B", d[:16])
                        
                        # TP Handler
                        payload = None
                        if mt in [0x20, 0x21, 0x22, 0xA0, 0xA1]: # TP Types
                            if len(d) >= 20: # 16 Header + 4 TP Header
                                tp_h = TpHeader.deserialize(d[16:20])
                                chunk = d[20:]
                                # Reassemble
                                full_payload = self.tp_reassembler.process_segment((sid, mid, cid, ssid), tp_h, chunk)
                                if full_payload:
                                    # Complete! Restore original MessageType for processing
                                    mt &= ~0x20 
                                    payload = full_payload
                        else:
                            # Normal Message
                            payload = d[16:length+8] # Extract payload based on length field
                        
                        if payload is not None:
                            if mt == MessageType.RESPONSE:
                                key = (sid, mid, ssid)
                                # print(f"DEBUG: Response for {key} ready. In pending? {key in self.pending_requests}")
                                if key in self.pending_requests: self.request_results[key] = payload; self.pending_requests.pop(key).set()
                            elif sid in self.services:
                                res = self.services[sid].handle({'method_id': mid}, payload)
                                if res:
                                    rc_val = 0
                                    pld = res
                                    if isinstance(res, tuple):
                                        rc_val, pld = res

                                    # Check for Segmentation
                                    MAX_SEG_PAYLOAD = 1392 # Conservative MTU - Headers
                                    if len(pld) > MAX_SEG_PAYLOAD:
                                        # Send Segmented
                                        segments = segment_payload(pld, MAX_SEG_PAYLOAD)
                                        base_mt = MessageType.RESPONSE_WITH_TP # 0xA0
                                        if rc_val != 0: base_mt = MessageType.ERROR_WITH_TP # 0xA1 check logic? Standard says Error can be segmented too.

                                        for tp_h, chunk in segments:
                                            final_pld = tp_h.serialize() + chunk
                                            h = struct.pack(">HHIHH4B", sid, mid, len(final_pld)+8, cid, ssid, pv, iv, base_mt, rc_val)
                                            try:
                                                if s.type == socket.SOCK_DGRAM: s.sendto(h + final_pld, a)
                                                else: s.sendall(h + final_pld)
                                                if len(segments) > 2: time.sleep(0.001)
                                            except Exception as e:
                                                self.logger.log(LogLevel.ERROR, "Runtime", f"Failed to send TP segment: {e}")
                                                break
                                    else:
                                        # Send Normal
                                        h = struct.pack(">HHIHH4B", sid, mid, len(pld)+8, cid, ssid, pv, iv, MessageType.RESPONSE, rc_val)
                                        try:
                                            if s.type == socket.SOCK_DGRAM: s.sendto(h + pld, a)
                                            else: s.sendall(h + pld)
                                        except Exception as e:
                                            self.logger.log(LogLevel.ERROR, "Runtime", f"Failed to send response: {e}")

    def _handle_sd_packet(self, data, addr, alias):
        off = 16
        if len(data) < off + 8: return
        le = struct.unpack(">I", data[off+4:off+8])[0]
        curr, end = off + 8, off + 8 + le
        while curr + 16 <= end:
            et, idx1, n1 = data[curr], data[curr+1], (data[curr+3] >> 4) & 0x0F
            sid, iid = struct.unpack(">HH", data[curr+4:curr+8])
            raw = struct.unpack(">I", data[curr+8:curr+12])[0]
            maj, ttl = (raw >> 24) & 0xFF, raw & 0xFFFFFF
            if et == 0x01 and ttl > 0:
                # Offer Service -> Add to remote services
                # Check find_on
                allowed = True
                if 'required' in self.config:
                    # Find req config for this sid
                    req = next((c for c in self.config['required'].values() if c.get('service_id') == sid), None)
                    if req:
                        find_on = req.get("find_on", [])
                        if find_on and alias not in find_on:
                            allowed = False

                if allowed:
                    opts = []
                    optr, oend = end + 4, end + 4 + struct.unpack(">I", data[end:end+4])[0]
                    while optr + 3 <= oend:
                        l, t = struct.unpack(">H", data[optr:optr+2])[0], data[optr+2]
                        if t == 0x04: opts.append((socket.inet_ntoa(data[optr+4:optr+8]), struct.unpack(">H", data[optr+10:optr+12])[0], ("tcp" if data[optr+9] == 6 else "udp")))
                        elif t == 0x06: opts.append((socket.inet_ntop(socket.AF_INET6, data[optr+4:optr+20]), struct.unpack(">H", data[optr+22:optr+24])[0], ("tcp" if data[optr+21] == 6 else "udp")))
                        else: opts.append(None)
                        optr += 3 + l
                    ep = opts[idx1] if n1 > 0 and idx1 < len(opts) else next((o for o in opts if o), None)
                    if ep: self.remote_services[(sid, maj)] = ep
            
            elif et == 0x00: 
                # Find Service
                # Check if we offer this service
                # [PRS_SOMEIPSD_00015] If a server receives a FindService... it shall send an OfferService.
                for (oid, oiid, omaj, omin, oip, op, opr, oa) in self.offered_services:
                    if oid == sid and (iid == 0xFFFF or iid == oiid):
                        # Match found! Send Unicast Offer to requester
                        self.logger.log(LogLevel.DEBUG, "Runtime", f"Received FindService for {sid:x}:{iid:x} from {addr}. Sending Unicast Offer.")
                        # Send Unicast Offer to the address that sent the FindService
                        self._send_offer(oid, oiid, omaj, omin, op, oip, opr, oa, target_addr=addr)

            curr += 16

    def _send_subscribe(self, sid, iid, egid, ttl, alias, is6):
        sock = self.sd_listeners.get(f"{alias}_{'v6' if is6 else 'v4'}")
        if not sock: return
        
        # Entry Type 0x06: SubscribeEventgroup
        # Index1, Index2, Num1, Num2
        # We need to include our endpoint option so the publisher knows where to send events.
        # Python runtime receives events on the same port as requests usually, or a specific one?
        # The runtime binds listeners based on 'endpoints'.
        # We need to pick a valid unicast endpoint on this interface to receive UDP events.
        
        # Find a listener on this interface that matches the IP version
        my_ip = None
        my_port = 0
        my_proto = "udp"
        
        for (lip, lport, lproto), s in self.listeners.items():
            # Check if lip belongs to this interface (simplified check: if is6 matches)
            if (":" in lip) == is6 and lproto == "udp":
                my_ip = lip
                my_port = lport
                break
        
        if not my_ip:
             # Fallback: try to find any IP on this interface from config
             eps = self.interfaces.get(alias, {}).get("endpoints", {})
             for ep in eps.values():
                 if (":" in ep["ip"]) == is6:
                     my_ip = ep["ip"]
                     my_port = ep.get("port", 0) # This might be 0 if dynamic, which is bad for subscription
                     break

        if not my_ip or my_port == 0:
            print(f"DEBUG: Could not find valid listening endpoint for Subscribe on {alias} {'v6' if is6 else 'v4'}")
            return

        # Construction
        # Entry: Type 0x06
        # Options: 1 option (our endpoint)
        # Struct packing:
        # Type(1), Index1(1), Index2(1), Num1|Num2(1)
        # SID(2), IID(2), MAJ|TTL(4), Reserved|Counter|EGID(4)
        
        min_val = (egid & 0xFFFF) | 0x00000000 
        # Actually in _send_offer we used min for the last 4 bytes completely.
        # But here EGID is 16 bits.
        # We put it in the lower 16 bits of the last field usually?
        # Or upper?
        # Looking at Rust: `minor_version: (eventgroup_id as u32) << 16`
        # So it implies upper 16 bits.
        # Let's match Rust.
        
        min_val = (egid << 16) & 0xFFFF0000
        
        pld = bytearray([0x80, 0, 0, 0]) + struct.pack(">I", 16) 
        pld += struct.pack(">BBBBHHII", 0x06, 0, 0, 1<<4, sid, iid, (1<<24)|ttl, min_val)

        # Options
        prid = 0x11 # UDP
        opt = struct.pack(">HBB", 0x0015 if is6 else 0x0009, 0x06 if is6 else 0x04, 0) + (socket.inet_pton(socket.AF_INET6, my_ip) if is6 else socket.inet_aton(my_ip)) + struct.pack(">BBH", 0, prid, my_port)
        pld += struct.pack(">I", len(opt)) + opt
        
        h = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, len(pld)+8, 0, 1, 1, 1, 2, 0)
        
        sd_sd = self.interfaces.get(alias, {}).get("sd", {})
        sd_ep_key = sd_sd.get(f"endpoint_{'v6' if is6 else 'v4'}") or sd_sd.get("endpoint")
        if not sd_ep_key: return
        
        tep = self.interfaces.get(alias, {}).get("endpoints", {}).get(sd_ep_key)

        if tep:
            try:
                sock.sendto(h + pld, (tep["ip"], tep["port"]))
            except Exception as e:
                self.logger.log(LogLevel.ERROR, "Runtime", f"Failed to send subscribe: {e}")

    def _send_offer(self, sid, iid, maj, min, p, ip, pr, alias, target_addr=None):
        sd = self.interfaces.get(alias, {}).get("sd", {})
        eps = self.interfaces.get(alias, {}).get("endpoints", {})
        if not sd or not eps: return
        is6, prid = (":" in ip), (6 if pr == 'tcp' else 0x11)
        # print(f"DEBUG: _send_offer sid={sid} ip={ip} p={p} pr={pr} -> prid={prid}")
        pld = bytearray([0x80, 0, 0, 0]) + struct.pack(">I", 16) + struct.pack(">BBBBHHII", 0x01, 0, 0, 1<<4, sid, iid, (maj<<24)|0xFFFFFF, min)
        opt = struct.pack(">HBB", 0x0015 if is6 else 0x0009, 0x06 if is6 else 0x04, 0) + (socket.inet_pton(socket.AF_INET6, ip) if is6 else socket.inet_aton(ip)) + struct.pack(">BBH", 0, prid, p)
        pld += struct.pack(">I", len(opt)) + opt
        h = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, len(pld)+8, 0, 1, 1, 1, 2, 0)
        sock = self.sd_listeners.get(f"{alias}_{'v6' if is6 else 'v4'}")
        
        # Determine destination: Unicast (target_addr) or Multicast (config)
        dest = target_addr
        if not dest:
            tep = eps.get(sd.get(f"endpoint_{'v6' if is6 else 'v4'}") or sd.get("endpoint"))
            if tep: dest = (tep["ip"], tep["port"])
            
        if sock and dest:
            try:
                sock.sendto(h + pld, dest)
            except:
                pass


    @staticmethod
    def _is_local_unicast(ip):
        try: return not ipaddress.ip_address(ip).is_multicast
        except: return False

    def _dump_packet(self, data, addr):
        if len(data) < 16: return
        sid, mid, _, _, _, _, _, mt, _ = struct.unpack(">HHIHH4B", data[:16])
        self.logger.log(LogLevel.DEBUG, "DUMP", f"SOME/IP {sid:04x}:{mid:04x} mt={mt} from {addr}")
