from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type
import struct

class PythonGenerator(AbstractGenerator):
    def generate(self, structs: list[Struct], services: list[Service], output_dir: str = "build/generated") -> dict[str, str]:
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
            runtime_lines.append(f"    MAJOR_VERSION = {svc.major_version}")
            runtime_lines.append(f"    MINOR_VERSION = {svc.minor_version}")
            runtime_lines.append(f"    def get_service_id(self): return self.SERVICE_ID")
            runtime_lines.append(f"    def get_major_version(self): return self.MAJOR_VERSION")
            runtime_lines.append(f"    def get_minor_version(self): return self.MINOR_VERSION")
            for m in svc.methods:
                runtime_lines.append(f"    METHOD_{m.name.upper()} = {m.id}")
            for e in svc.events:
                runtime_lines.append(f"    EVENT_{e.name.upper()} = {e.id}")
            for f in svc.fields:
                if f.get_id: runtime_lines.append(f"    FIELD_GET_{f.name.upper()} = {f.get_id}")
                if f.set_id: runtime_lines.append(f"    FIELD_SET_{f.name.upper()} = {f.set_id}")
                if f.notifier_id: runtime_lines.append(f"    EVENT_{f.name.upper()}_NOTIFY = {f.notifier_id}")
            
            runtime_lines.append("    def handle(self, header, payload):")
            runtime_lines.append("        mid = header['method_id']")
            runtime_lines.append(f"        print(f'DEBUG: {svc.name} handling method {{mid}}')")
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
            runtime_lines.append(f"    MAJOR_VERSION = {svc.major_version}")
            runtime_lines.append(f"    MINOR_VERSION = {svc.minor_version}")
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
                wait_for_res = m.ret_type.name != "None"
                runtime_lines.append("        if target:")
                runtime_lines.append(f"            res_payload = self.runtime.send_request(self.SERVICE_ID, {m.id}, req.serialize(), target, wait_for_response={wait_for_res})")
                if wait_for_res:
                    res_name = f"{svc.name}{method_pascal}Response"
                    runtime_lines.append(f"            if res_payload:")
                    runtime_lines.append(f"                res_obj = {res_name}.deserialize(res_payload)")
                    runtime_lines.append(f"                return res_obj.result")
                    runtime_lines.append(f"            return None")
            runtime_lines.append("")

        import os
        return {
            os.path.join(output_dir, "python/bindings.py"): "\n".join(bind_lines),
            os.path.join(output_dir, "python/runtime.py"): "\n".join(runtime_lines)
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
            lines.append(self._ser_val_py(f"self.{f.name}", f.type, indent="        "))
        lines.append("        return bytes(buffer)")

        lines.append("    @staticmethod")
        lines.append("    def deserialize(data: bytes) -> '" + s.name + "':")
        lines.append("        return " + s.name + ".deserialize_from(data, 0)[0]")

        lines.append("    @staticmethod")
        lines.append("    def deserialize_from(data: bytes, off: int) -> tuple['" + s.name + "', int]:")
        lines.append("        obj = " + s.name + "()")
        lines.append("        start_off = off")
        for f in s.fields:
            lines.append(self._deser_val_py(f"obj.{f.name}", f.type, indent="        "))
        lines.append("        return obj, off - start_off")
        return "\n".join(lines)

    def _ser_val_py(self, expr: str, t: Type, indent: str) -> str:
        lines = []
        if t.inner: # List
             lines.append(f"{indent}if {expr} is None: {expr} = []")
             lines.append(f"{indent}_t_buf = bytearray()")
             lines.append(f"{indent}for _item in {expr}:")
             lines.append(f"{indent}    # Recursively append to _t_buf")
             lines.append(f"{indent}    _orig_buf = buffer")
             lines.append(f"{indent}    buffer = _t_buf")
             lines.append(self._ser_val_py("_item", t.inner, indent + "    "))
             lines.append(f"{indent}    buffer = _orig_buf")
             lines.append(f"{indent}buffer.extend(struct.pack('>I', len(_t_buf)))")
             lines.append(f"{indent}buffer.extend(_t_buf)")
        elif t.name in ('int', 'int32'): lines.append(f"{indent}buffer.extend(struct.pack('>i', {expr} or 0))")
        elif t.name == 'int8': lines.append(f"{indent}buffer.extend(struct.pack('>b', {expr} or 0))")
        elif t.name == 'int16': lines.append(f"{indent}buffer.extend(struct.pack('>h', {expr} or 0))")
        elif t.name == 'int64': lines.append(f"{indent}buffer.extend(struct.pack('>q', {expr} or 0))")
        elif t.name == 'uint8': lines.append(f"{indent}buffer.extend(struct.pack('>B', {expr} or 0))")
        elif t.name == 'uint16': lines.append(f"{indent}buffer.extend(struct.pack('>H', {expr} or 0))")
        elif t.name == 'uint32': lines.append(f"{indent}buffer.extend(struct.pack('>I', {expr} or 0))")
        elif t.name == 'uint64': lines.append(f"{indent}buffer.extend(struct.pack('>Q', {expr} or 0))")
        elif t.name in ('float', 'float32'): lines.append(f"{indent}buffer.extend(struct.pack('>f', {expr} or 0.0))")
        elif t.name in ('double', 'float64'): lines.append(f"{indent}buffer.extend(struct.pack('>d', {expr} or 0.0))")
        elif t.name == 'bool': lines.append(f"{indent}buffer.extend(struct.pack('>?', {expr} or False))")
        elif t.name in ('str', 'string'):
             lines.append(f"{indent}_b = ({expr} or '').encode('utf-8')")
             lines.append(f"{indent}buffer.extend(struct.pack('>I', len(_b)) + _b)")
        else: # Struct
             lines.append(f"{indent}if {expr}: buffer.extend({expr}.serialize())")
        return "\n".join(lines)

    def _deser_val_py(self, expr_target: str, t: Type, indent: str) -> str:
        lines = []
        if t.inner:
             lines.append(f"{indent}_l = struct.unpack_from('>I', data, off)[0]; off += 4")
             lines.append(f"{indent}_e = off + _l")
             lines.append(f"{indent}_items = []")
             lines.append(f"{indent}while off < _e:")
             # Recurse
             lines.append(self._deser_val_py("_sub", t.inner, indent + "    "))
             lines.append(f"{indent}    _items.append(_sub)")
             lines.append(f"{indent}{expr_target} = _items")
        elif t.name in ('int', 'int32'): lines.append(f"{indent}{expr_target} = struct.unpack_from('>i', data, off)[0]; off += 4")
        elif t.name == 'int8': lines.append(f"{indent}{expr_target} = struct.unpack_from('>b', data, off)[0]; off += 1")
        elif t.name == 'int16': lines.append(f"{indent}{expr_target} = struct.unpack_from('>h', data, off)[0]; off += 2")
        elif t.name == 'int64': lines.append(f"{indent}{expr_target} = struct.unpack_from('>q', data, off)[0]; off += 8")
        elif t.name == 'uint8': lines.append(f"{indent}{expr_target} = struct.unpack_from('>B', data, off)[0]; off += 1")
        elif t.name == 'uint16': lines.append(f"{indent}{expr_target} = struct.unpack_from('>H', data, off)[0]; off += 2")
        elif t.name == 'uint32': lines.append(f"{indent}{expr_target} = struct.unpack_from('>I', data, off)[0]; off += 4")
        elif t.name == 'uint64': lines.append(f"{indent}{expr_target} = struct.unpack_from('>Q', data, off)[0]; off += 8")
        elif t.name in ('float', 'float32'): lines.append(f"{indent}{expr_target} = struct.unpack_from('>f', data, off)[0]; off += 4")
        elif t.name in ('double', 'float64'): lines.append(f"{indent}{expr_target} = struct.unpack_from('>d', data, off)[0]; off += 8")
        elif t.name == 'bool': lines.append(f"{indent}{expr_target} = struct.unpack_from('>?', data, off)[0]; off += 1")
        elif t.name in ('str', 'string'):
             lines.append(f"{indent}_slen = struct.unpack_from('>I', data, off)[0]; off += 4")
             lines.append(f"{indent}{expr_target} = data[off:off+_slen].decode('utf-8'); off += _slen")
        else: # Struct
             lines.append(f"{indent}{expr_target}, _c = {t.name}.deserialize_from(data, off)")
             lines.append(f"{indent}off += _c")
        return "\n".join(lines)
