from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type
import struct

class PythonGenerator(AbstractGenerator):
    def generate(self, structs: list[Struct], services: list[Service]) -> dict[str, str]:
        # 1. Bindings
        bind_lines = [
            "import struct",
            "from typing import List, Any",
            "",
            "class SomeIpMessage: pass",
            ""
        ]
        
        for s in structs:
            bind_lines.append(self._generate_struct(s))
            bind_lines.append("")

        for svc in services:
            bind_lines.append(f"# --- Service {svc.name} ---")
            for m in svc.methods:
                method_pascal = m.name.title().replace('_', '')
                req_name = f"{svc.name}{method_pascal}Request"
                bind_lines.append(self._generate_struct(Struct(req_name, m.args)))
                res_name = f"{svc.name}{method_pascal}Response"
                res_fields = []
                if m.ret_type.name != "None":
                    res_fields.append(Field("result", m.ret_type))
                bind_lines.append(self._generate_struct(Struct(res_name, res_fields)))
                bind_lines.append("")

            for f in svc.fields:
                if f.get_id:
                     res_name = f"{svc.name}Get{f.name.title().replace('_', '')}Response"
                     bind_lines.append(self._generate_struct(Struct(res_name, [Field("value", f.type)])))
                if f.set_id:
                     req_name = f"{svc.name}Set{f.name.title().replace('_', '')}Request"
                     bind_lines.append(self._generate_struct(Struct(req_name, [Field("value", f.type)])))
                     res_name = f"{svc.name}Set{f.name.title().replace('_', '')}Response"
                     bind_lines.append(self._generate_struct(Struct(res_name, [])))
            
            for e in svc.events:
                event_pascal = e.name.title().replace('_', '')
                event_name = f"{svc.name}{event_pascal}Event"
                bind_lines.append(self._generate_struct(Struct(event_name, e.args)))
                bind_lines.append("")

        # 2. Runtime (Stubs & Clients)
        runtime_lines = [
            "import struct",
            "from typing import Dict, Any, List",
            "from fusion_hawking import SomeIpRuntime, RequestHandler, LogLevel",
            "from bindings import *",
            ""
        ]
        
        for svc in services:
            # Stub
            runtime_lines.append(f"class {svc.name}Stub(RequestHandler):")
            runtime_lines.append(f"    SERVICE_ID = {svc.id}")
            runtime_lines.append(f"    def get_service_id(self): return self.SERVICE_ID")
            runtime_lines.append("    def handle(self, header, payload):")
            runtime_lines.append("        mid = header['method_id']")
            for m in svc.methods:
                method_pascal = m.name.title().replace('_', '')
                runtime_lines.append(f"        if mid == {m.id}:")
                runtime_lines.append(f"            req = {svc.name}{method_pascal}Request.deserialize(payload)")
                args_call = ", ".join([f"req.{f.name}" for f in m.args])
                runtime_lines.append(f"            result = self.{m.name}({args_call})")
                res_name = f"{svc.name}{method_pascal}Response"
                if m.ret_type.name != "None":
                    runtime_lines.append(f"            res = {res_name}(result)")
                else:
                    runtime_lines.append(f"            res = {res_name}()")
                runtime_lines.append("            return res.serialize()")
            runtime_lines.append("        return None")
            for m in svc.methods:
                method_pascal = m.name.title().replace('_', '')
                runtime_lines.append(f"    def {m.name}(self, {', '.join([a.name for a in m.args])}): raise NotImplementedError()")
            
            for f in svc.fields:
                if f.get_id:
                     runtime_lines.append(f"    def get_{f.name}(self): raise NotImplementedError()")
                if f.set_id:
                     runtime_lines.append(f"    def set_{f.name}(self, value): raise NotImplementedError()")
            
            for e in svc.events:
                event_pascal = e.name.title().replace('_', '')
                runtime_lines.append(f"    def notify_{e.name}(self, {', '.join([a.name for a in e.args])}, target=None):")
                runtime_lines.append(f"        req = {svc.name}{event_pascal}Event({', '.join([a.name for a in e.args])})")
                runtime_lines.append(f"        if target: self.runtime.send_request(self.SERVICE_ID, {e.id}, req.serialize(), target, msg_type=0x02)")
            runtime_lines.append("")

            # Client
            runtime_lines.append(f"class {svc.name}Client:")
            runtime_lines.append(f"    SERVICE_ID = {svc.id}")
            runtime_lines.append("    def __init__(self, runtime, alias=None):")
            runtime_lines.append("        self.runtime = runtime")
            runtime_lines.append("        self.alias = alias")
            runtime_lines.append("        self.event_handlers = {}")
            
            runtime_lines.append("    def on_event(self, mid, payload):")
            has_event = False
            for e in svc.events:
                event_pascal = e.name.title().replace('_', '')
                runtime_lines.append(f"        if mid == {e.id}:")
                runtime_lines.append(f"            ev = {svc.name}{event_pascal}Event.deserialize(payload)")
                runtime_lines.append(f"            if '{e.name}' in self.event_handlers: self.event_handlers['{e.name}'](ev)")
                has_event = True
            if not has_event: runtime_lines.append("        pass")
            for m in svc.methods:
                method_pascal = m.name.title().replace('_', '')
                args = ", ".join([f.name for f in m.args])
                runtime_lines.append(f"    def {m.name}(self, {args}):")
                runtime_lines.append(f"        req = {svc.name}{method_pascal}Request()")
                for f in m.args:
                    runtime_lines.append(f"        req.{f.name} = {f.name}")
                runtime_lines.append(f"        target = self.runtime.remote_services.get(self.SERVICE_ID)")
                runtime_lines.append(f"        if not target and self.runtime.config and 'required' in self.runtime.config:")
                runtime_lines.append(f"            cfg = self.runtime.config['required'].get(self.alias)")
                runtime_lines.append(f"            if cfg and 'static_ip' in cfg:")
                runtime_lines.append(f"                target = (cfg['static_ip'], cfg.get('static_port', 0))")
                runtime_lines.append("        if target:")
                runtime_lines.append(f"            self.runtime.send_request(self.SERVICE_ID, {m.id}, req.serialize(), target)")
            runtime_lines.append("")

        return {
            "build/generated/python/bindings.py": "\n".join(bind_lines),
            "build/generated/python/runtime.py": "\n".join(runtime_lines)
        }

    def _generate_struct(self, s: Struct) -> str:
        lines = [f"class {s.name}:"]
        # Use name=None for all arguments to avoid positional argument errors
        arg_list = ", ".join([f"{f.name}=None" for f in s.fields])
        if arg_list:
            lines.append(f"    def __init__(self, {arg_list}):")
            for f in s.fields: lines.append(f"        self.{f.name} = {f.name}")
        else:
            lines.append(f"    def __init__(self): pass")

        lines.append("    def serialize(self) -> bytes:")
        lines.append("        buffer = bytearray()")
        for f in s.fields:
            if f.type.is_list:
                lines.append(f"        if self.{f.name} is None: self.{f.name} = []")
                lines.append(f"        temp = bytearray()")
                lines.append(f"        for item in self.{f.name}: temp.extend(struct.pack('>i', item))")
                lines.append(f"        buffer.extend(struct.pack('>I', len(temp)))")
                lines.append(f"        buffer.extend(temp)")
            elif f.type.name == 'int':
                lines.append(f"        buffer.extend(struct.pack('>i', self.{f.name} or 0))")
            elif f.type.name == 'str':
                lines.append(f"        b = (self.{f.name} or '').encode('utf-8')")
                lines.append(f"        buffer.extend(struct.pack('>I', len(b)))")
                lines.append(f"        buffer.extend(b)")
        lines.append("        return bytes(buffer)")

        lines.append("    @staticmethod")
        lines.append("    def deserialize(data: bytes) -> '" + s.name + "':")
        lines.append("        obj = " + s.name + "()")
        lines.append("        off = 0")
        for f in s.fields:
            if f.type.is_list:
                lines.append(f"        len_field = struct.unpack_from('>I', data, off)[0]; off += 4")
                lines.append(f"        count = len_field // 4")
                lines.append(f"        obj.{f.name} = list(struct.unpack_from(f'>{{count}}i', data, off)); off += len_field")
            elif f.type.name == 'int':
                lines.append(f"        obj.{f.name} = struct.unpack_from('>i', data, off)[0]; off += 4")
            elif f.type.name == 'str':
                lines.append(f"        len_field = struct.unpack_from('>I', data, off)[0]; off += 4")
                lines.append(f"        obj.{f.name} = data[off:off+len_field].decode('utf-8'); off += len_field")
        lines.append("        return obj")
        return "\n".join(lines)
