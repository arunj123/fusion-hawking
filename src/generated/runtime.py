
import socket
import struct
import threading
import time
import select
import json
import os
import sys

# --- Logging Abstraction ---
class LogLevel:
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

class Logger:
    def log(self, level, component, msg):
        pass

class ConsoleLogger(Logger):
    def log(self, level, component, msg):
        lvl_str = ["DEBUG", "INFO ", "WARN ", "ERROR"][level]
        print(f"[{lvl_str}] [{component}] {msg}")

# --- Runtime ---
class SomeIpRuntime:
    def __init__(self, config_path, instance_name, logger=None):
        self.logger = logger if logger else ConsoleLogger()
        self.config = self._load_config(config_path, instance_name)
        
        # Determine Bind Port
        # Use first providing service port or 0
        bind_port = 0
        if self.config and 'providing' in self.config:
            vals = list(self.config['providing'].values())
            if vals and 'port' in vals[0]:
                bind_port = vals[0]['port']
                
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(("0.0.0.0", bind_port))
        except:
             self.logger.log(LogLevel.WARN, "Runtime", f"Failed to bind port {bind_port}, binding 0")
             self.sock.bind(("0.0.0.0", 0))
             
        self.port = self.sock.getsockname()[1]
        self.logger.log(LogLevel.INFO, "Runtime", f"Initializing '{instance_name}' on port {self.port}")

        self.services = {} # id -> stub
        self.remote_services = {} # id -> (ip, port)
        self.offered_services = [] # list of (alias, stub)
        self.last_offer_time = 0
        self.running = True
        
        # SD Socket
        self.sd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sd_sock.bind(('0.0.0.0', 30490))
            mreq = struct.pack("4sl", socket.inet_aton('224.0.0.1'), socket.INADDR_ANY)
            self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self.sd_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        except:
            self.logger.log(LogLevel.WARN, "Runtime", "Could not bind SD multicast 30490")
            
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _load_config(self, path, name):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return data['instances'].get(name, {})
        except Exception as e:
            # print(f"Config Error: {e}") # Logger not init yet usually, but maybe?
            return {}

    def offer_service(self, alias, stub):
        # Resolve Config
        service_id = stub.SERVICE_ID
        port = self.port
        instance_id = 1
        
        if self.config and 'providing' in self.config:
            cfg = self.config['providing'].get(alias)
            if cfg:
                service_id = cfg.get('service_id', service_id)
                instance_id = cfg.get('instance_id', 1)
                port = cfg.get('port', self.port)
        
        self.services[service_id] = stub
        self.offered_services.append((alias, stub, service_id, instance_id, port))
        
        self.logger.log(LogLevel.INFO, "Runtime", f"Offered Service '{alias}' (0x{service_id:04x}) on port {port}")
        self._send_offer(service_id, instance_id, port)

    def _send_offer(self, service_id, instance_id, port):
        # ... (Same as before)
        # Assuming unchanged logic for packet construction, omitting full body for brevity in this step if possible?
        # No, must include full body in replacement.
        
        flags_res = 0x80000000
        opt_len_val = 9
        opt_type = 0x04
        opt_res = 0
        ip_bytes = socket.inet_aton('127.0.0.1')
        opt_res2 = 0
        proto = 0x11
        
        option = struct.pack(">HBB4sBBH", opt_len_val, opt_type, opt_res, ip_bytes, opt_res2, proto, port)
        
        len_entries = 16
        entry_type = 0x01
        idx1 = 0
        idx2 = 0
        num_opts_byte = (1 << 4) 
        
        major = 1
        ttl = 0xFFFFFF
        minor = 0
        maj_ttl = (major << 24) | ttl
        
        entry = struct.pack(">BBBBHHII", entry_type, idx1, idx2, num_opts_byte, service_id, instance_id, maj_ttl, minor)
        
        header = struct.pack(">II", flags_res, len_entries)
        opt_len_field = struct.pack(">I", len(option))
        
        msg = header + entry + opt_len_field + option
        try:
            self.sd_sock.sendto(msg, ('224.0.0.1', 30490))
        except: pass

    def get_client(self, alias, client_cls):
        return client_cls(self, alias)

    def send_request(self, alias, service_id, payload):
        target = ('127.0.0.1', 30509) # Default
        
        if service_id in self.remote_services:
            target = self.remote_services[service_id]
        elif self.config and 'required' in self.config:
            cfg = self.config['required'].get(alias)
            if cfg and 'static_ip' in cfg:
                 target = (cfg['static_ip'], cfg.get('static_port', 0))
        
        self.sock.sendto(payload, target)

    def _run(self):
        while self.running:
            now = time.time()
            if now - self.last_offer_time > 2.0:
                self.last_offer_time = now
                for (alias, stub, sid, iid, port) in self.offered_services:
                    self._send_offer(sid, iid, port)
            
            r, _, _ = select.select([self.sock, self.sd_sock], [], [], 0.5)
            for s in r:
                try:
                    data, addr = s.recvfrom(1500)
                    if s == self.sock:
                        if len(data) >= 16:
                            svc_id = struct.unpack(">H", data[:2])[0]
                            stub = self.services.get(svc_id)
                            if stub:
                                stub.handle_request(data, addr, self.sock)
                    elif s == self.sd_sock:
                        pass 
                except: pass
