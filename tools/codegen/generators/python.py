from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type

class PythonGenerator(AbstractGenerator):
    def generate(self, structs: list[Struct], services: list[Service]) -> dict[str, str]:
        lines = [
            "import struct", 
            "from typing import List, Any", 
            "import socket",
            "import threading",
            "import time",
            "",
            "class SomeIpMessage: pass",
            "def pack_u32(val): return struct.pack('>I', val)",
            "def unpack_u32(data, off): return struct.unpack_from('>I', data, off)[0], off+4",
            ""
        ]
        
        for s in structs:
            lines.append(self._generate_struct(s))
            lines.append("")

        for svc in services:
            lines.append(f"# --- Service {svc.name} ---")
            
            for m in svc.methods:
                method_pascal = m.name.title().replace('_', '')
                
                # Request
                req_name = f"{svc.name}{method_pascal}Request"
                lines.append(self._generate_struct(Struct(req_name, m.args)))
                
                # Response
                res_name = f"{svc.name}{method_pascal}Response"
                res_fields = []
                if m.ret_type.name != "None":
                    res_fields.append(Field("result", m.ret_type))
                lines.append(self._generate_struct(Struct(res_name, res_fields)))
                lines.append("")

            # Server Stub
            lines.append(self._generate_server_stub(svc))
            
            # Client
            lines.append(self._generate_client(svc))

        return {"build/generated/python/bindings.py": "\n".join(lines), "build/generated/python/runtime.py": self._generate_runtime_code()}

    def _generate_runtime_code(self) -> str:
        return """
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
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        lvl_str = ["DEBUG", "INFO ", "WARN ", "ERROR"][level]
        print(f"[{ts}] [{lvl_str}] [{component}] {msg}")

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
        # Build SD payload
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
        
        sd_header = struct.pack(">II", flags_res, len_entries)
        opt_len_field = struct.pack(">I", len(option))
        
        sd_payload = sd_header + entry + opt_len_field + option
        
        # SOME/IP Header for SD (service=0xFFFF, method=0x8100)
        payload_len = len(sd_payload) + 8  # +8 for client_id to return_code
        someip_header = struct.pack(">HHIHH4B",
            0xFFFF,  # service_id
            0x8100,  # method_id
            payload_len,  # length
            0x0000,  # client_id
            0x0001,  # session_id
            0x01, 0x01, 0x02, 0x00  # proto_ver, iface_ver, msg_type, ret_code
        )
        
        msg = someip_header + sd_payload
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
                        # Parse SD offer packet
                        # SOME/IP Header: 16 bytes
                        # SD Payload: flags(4) + entries_len(4) + entry(16) + opts_len(4) + option(...)
                        # Entry: type(1)+idx1(1)+idx2(1)+num_opts(1)+service_id(2)+instance_id(2)+ver_ttl(4)+minor(4)
                        # Option IPv4: length(2)+type(1)+res(1)+ip(4)+res(1)+proto(1)+port(2)
                        if len(data) >= 56:
                            # Service ID at offset 16+4+4+4 = 28-29
                            service_id = struct.unpack(">H", data[28:30])[0]
                            # IP at offset 16+4+4+16+4+4 = 48-51
                            ip_bytes = data[48:52]
                            ip_str = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
                            # Port at offset 16+4+4+16+4+10 = 54-55
                            port = struct.unpack(">H", data[54:56])[0]
                            if ip_str != "0.0.0.0" and port > 0 and ip_str != "127.0.0.1":
                                self.remote_services[service_id] = (ip_str, port)
                                self.logger.log(LogLevel.DEBUG, "SD", f"Discovered 0x{service_id:04x} at {ip_str}:{port}")
                            elif ip_str == "127.0.0.1" and port > 0:
                                # Local loopback, still register
                                self.remote_services[service_id] = (ip_str, port)
                                self.logger.log(LogLevel.DEBUG, "SD", f"Discovered 0x{service_id:04x} at {ip_str}:{port}")
                except: pass
"""

    def _generate_struct(self, s: Struct) -> str:
        lines = []
        lines.append(f"class {s.name}:")
        args = [f"{f.name}" for f in s.fields]
        
        if args:
            lines.append(f"    def __init__(self, {', '.join(args)}):")
            for f in s.fields: lines.append(f"        self.{f.name} = {f.name}")
        else:
            lines.append(f"    def __init__(self): pass")

        lines.append("    def serialize(self) -> bytes:")
        lines.append(self._gen_serialization_logic(s.fields))
        return "\n".join(lines)

    def _gen_serialization_logic(self, fields: list[Field], indent="        ") -> str:
        code = []
        code.append(f"{indent}buffer = bytearray()")
        if not fields:
             code.append(f"{indent}return b''")
             return "\n".join(code)

        for f in fields:
             if f.type.is_list:
                 code.append(f"{indent}temp_buf = bytearray()")
                 code.append(f"{indent}for item in self.{f.name}:")
                 code.append(f"{indent}    temp_buf.extend(struct.pack('>i', item))") # Assuming int list
                 code.append(f"{indent}buffer.extend(struct.pack('>I', len(temp_buf)))")
                 code.append(f"{indent}buffer.extend(temp_buf)")
             elif f.type.name == 'int':
                 code.append(f"{indent}buffer.extend(struct.pack('>i', self.{f.name}))")
             elif f.type.name == 'str':
                 code.append(f"{indent}b = self.{f.name}.encode('utf-8')")
                 code.append(f"{indent}buffer.extend(struct.pack('>I', len(b)))")
                 code.append(f"{indent}buffer.extend(b)")
        code.append(f"{indent}return bytes(buffer)")
        return "\n".join(code)

    def _generate_server_stub(self, svc: Service) -> str:
        lines = []
        lines.append(f"class {svc.name}Stub:")
        lines.append(f"    SERVICE_ID = {hex(svc.id)}")
        lines.append(f"    def handle_request(self, data, addr, sock):")
        lines.append(f"        if len(data) < 16: return False")
        lines.append(f"        svc_id, method_id, length, req_id, proto, ver, type_, ret = struct.unpack('>HHIIBBBB', data[:16])")
        lines.append(f"        if svc_id != self.SERVICE_ID: return False")
        lines.append(f"        payload = data[16:]")
        lines.append(f"        ")
        
        for m in svc.methods:
            method_pascal = m.name.title().replace('_', '')
            req_name = f"{svc.name}{method_pascal}Request"
            res_name = f"{svc.name}{method_pascal}Response"
            
            lines.append(f"        if method_id == {m.id}:")
            lines.append(f"            # Deserialize {req_name}")
            lines.append(f"            off = 0")
            
            args_call = []
            for f in m.args:
                if f.type.name == 'int':
                    lines.append(f"            {f.name} = struct.unpack_from('>i', payload, off)[0]; off+=4")
                elif f.type.name == 'str':
                    lines.append(f"            l = struct.unpack_from('>I', payload, off)[0]; off+=4")
                    lines.append(f"            {f.name} = payload[off:off+l].decode('utf-8'); off+=l")
                elif f.type.is_list: # Only int list supported
                     lines.append(f"            l = struct.unpack_from('>I', payload, off)[0]; off+=4")
                     lines.append(f"            # Assuming int list")
                     lines.append(f"            count = l // 4")
                     lines.append(f"            {f.name} = list(struct.unpack_from(f'>{{count}}i', payload, off)); off+=l")
                args_call.append(f.name)
            
            lines.append(f"            result = self.{m.name}({', '.join(args_call)})")
            
            if m.ret_type.name != "None":
                 lines.append(f"            resp = {res_name}(result)")
            else:
                 lines.append(f"            resp = {res_name}()")
                 
            lines.append(f"            res_payload = resp.serialize()")
            lines.append(f"            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)")
            lines.append(f"            sock.sendto(hdr + res_payload, addr)")
            lines.append(f"            return True")
            
        lines.append(f"        return False")
        return "\n".join(lines)

    def _generate_client(self, svc: Service) -> str:
        lines = []
        lines.append(f"class {svc.name}Client:")
        lines.append(f"    SERVICE_ID = {hex(svc.id)}")
        lines.append(f"    def __init__(self, runtime, alias=None):")
        lines.append(f"        self.runtime = runtime")
        lines.append(f"        self.alias = alias")
        
        for m in svc.methods:
            args = [f.name for f in m.args]
            sig = ", ".join(["self"] + args)
            lines.append(f"    def {m.name}({sig}):")
            
            method_pascal = m.name.title().replace('_', '')
            req_name = f"{svc.name}{method_pascal}Request"
            init_args = ", ".join(args)
            if init_args:
                lines.append(f"        req = {req_name}({init_args})")
            else:
                lines.append(f"        req = {req_name}()")
                
            lines.append(f"        payload = req.serialize()")
            lines.append(f"        hdr = struct.pack('>HHIIBBBB', {svc.id}, {m.id}, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)")
            lines.append(f"        self.runtime.send_request(self.alias, {svc.id}, hdr + payload)")
            lines.append("")
        return "\n".join(lines)
