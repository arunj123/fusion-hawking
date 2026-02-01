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

        return {"src/generated/bindings.py": "\n".join(lines)}

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
        lines.append(f"    def __init__(self, sock, addr):")
        lines.append(f"        self.sock = sock")
        lines.append(f"        self.addr = addr")
        
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
            lines.append(f"        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret")
            lines.append(f"        hdr = struct.pack('>HHIIBBBB', {svc.id}, {m.id}, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)")
            lines.append(f"        self.sock.sendto(hdr + payload, self.addr)")
            lines.append("")
        return "\n".join(lines)
