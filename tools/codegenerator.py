import ast
import sys
import os

# --- Type Helpers ---
def parse_type(annotation):
    if isinstance(annotation, ast.Name):
        return annotation.id
    elif isinstance(annotation, ast.Subscript): # For List[int]
        if isinstance(annotation.value, ast.Name) and annotation.value.id == 'List':
            inner = parse_type(annotation.slice)
            return f"Vec<{inner}>"
    elif isinstance(annotation, ast.Constant) and annotation.value is None:
        return "None"
    return "Unknown"

def rust_type(py_type):
    mapping = { 'int': 'i32', 'float': 'f32', 'str': 'String', 'bool': 'bool', 'None': '()' }
    if py_type in mapping: return mapping[py_type]
    if py_type.startswith("Vec<"):
        inner = py_type[4:-1]
        return f"Vec<{rust_type(inner)}>"
    return py_type

def cpp_type(py_type):
    mapping = { 'int': 'int32_t', 'float': 'float', 'str': 'std::string', 'bool': 'bool', 'None': 'void' }
    if py_type in mapping: return mapping[py_type]
    if py_type.startswith("Vec<"):
        inner = py_type[4:-1]
        return f"std::vector<{cpp_type(inner)}>"
    return py_type

# --- AST Parsing ---
class ServiceMethod:
    def __init__(self, name, id, args, ret_type):
        self.name = name
        self.id = id
        self.args = args # list of (name, type)
        self.ret_type = ret_type

class ServiceDef:
    def __init__(self, name, id, methods):
        self.name = name
        self.id = id
        self.methods = methods

class StructDef:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields # list of (name, type)

def parse_valid_id(decorators, target):
    for d in decorators:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == target:
            for kw in d.keywords:
                if kw.arg == 'id':
                    return kw.value.value # integer
    return None

def parse_file(filepath):
    with open(filepath, "r") as f:
        tree = ast.parse(f.read())

    structs = []
    services = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # Check for @dataclass (Struct)
            is_dataclass = any(isinstance(d, ast.Name) and d.id == 'dataclass' for d in node.decorator_list)
            if is_dataclass:
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign):
                        name = item.target.id
                        type_str = parse_type(item.annotation)
                        fields.append((name, type_str))
                structs.append(StructDef(node.name, fields))
                continue

            # Check for @service (Service)
            service_id = parse_valid_id(node.decorator_list, 'service')
            if service_id is not None:
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_id = parse_valid_id(item.decorator_list, 'method')
                        if method_id is not None:
                            args = []
                            for arg in item.args.args:
                                if arg.arg == 'self': continue
                                if arg.annotation:
                                    args.append((arg.arg, parse_type(arg.annotation)))
                            ret = "None"
                            if item.returns:
                                ret = parse_type(item.returns)
                            methods.append(ServiceMethod(item.name, method_id, args, ret))
                services.append(ServiceDef(node.name, service_id, methods))

    return structs, services

# --- Rust Generation ---
def generate_rust_struct(name, fields):
    lines = []
    lines.append(f"#[derive(Debug, Clone, PartialEq)]")
    lines.append(f"pub struct {name} {{")
    for fname, ftype in fields:
        lines.append(f"    pub {fname}: {rust_type(ftype)},")
    lines.append("}")
    
    # Serialize
    lines.append(f"impl SomeIpSerialize for {name} {{")
    lines.append(f"    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {{")
    for fname, _ in fields:
        lines.append(f"        self.{fname}.serialize(writer)?;")
    lines.append("        Ok(())")
    lines.append("    }")
    lines.append("}")
    
    # Deserialize
    lines.append(f"impl SomeIpDeserialize for {name} {{")
    lines.append(f"    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {{")
    lines.append(f"        Ok({name} {{")
    for fname, ftype in fields:
            lines.append(f"            {fname}: <{rust_type(ftype)}>::deserialize(reader)?,")
    lines.append("        })")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines)

def generate_rust(structs, services):
    lines = [
        "use crate::codec::{SomeIpSerialize, SomeIpDeserialize, SomeIpHeader};",
        "use std::io::{Result, Write, Read, Cursor};",
        "use std::sync::{Arc, Mutex};",
        "use crate::transport::{UdpTransport, SomeIpTransport};",
        "use crate::ServiceDiscovery;",
        "use std::net::SocketAddr;",
        ""
    ]

    # ... Structs ...
    for s in structs:
        lines.append(generate_rust_struct(s.name, s.fields))
        lines.append("")

    # ... Services ...
    for svc in services:
        lines.append(f"// --- Service: {svc.name} (ID: {hex(svc.id)}) ---")
        
        for m in svc.methods:
            # PascalCase helper
            method_pascal = m.name.title().replace('_', '')
            
            # Request
            req_name = f"{svc.name}{method_pascal}Request"
            lines.append(generate_rust_struct(req_name, m.args))
            
            # Response
            res_name = f"{svc.name}{method_pascal}Response"
            res_fields = [("result", m.ret_type)] if m.ret_type != "None" else []
            lines.append(generate_rust_struct(res_name, res_fields))
            lines.append("")

        # Provider Trait
        lines.append(f"pub trait {svc.name}Provider: Send + Sync {{")
        for m in svc.methods:
            args_str = ", ".join([f"{a[0]}: {rust_type(a[1])}" for a in m.args])
            ret_str = f" -> {rust_type(m.ret_type)}" if m.ret_type != "None" else ""
            lines.append(f"    fn {m.name}(&self, {args_str}){ret_str};")
        lines.append("}")
        lines.append("")

        # Server Stub
        lines.append(f"pub struct {svc.name}Server<T: {svc.name}Provider> {{")
        lines.append("    provider: Arc<T>,")
        lines.append("}")
        lines.append(f"impl<T: {svc.name}Provider> {svc.name}Server<T> {{")
        lines.append("    pub fn new(provider: Arc<T>) -> Self { Self { provider } }")
        
        lines.append("    pub fn handle_request(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>> {")
        lines.append(f"        if header.service_id != {svc.id} {{ return None; }}")
        lines.append("        match header.method_id {")
        for m in svc.methods:
            method_pascal = m.name.title().replace('_', '')
            req_name = f"{svc.name}{method_pascal}Request"
            res_name = f"{svc.name}{method_pascal}Response"
            lines.append(f"            {m.id} => {{")
            lines.append(f"                let mut cursor = Cursor::new(payload);")
            lines.append(f"                if let Ok(req) = {req_name}::deserialize(&mut cursor) {{")
            
            call_args = ", ".join([f"req.{a[0]}" for a in m.args])
            lines.append(f"                    let result = self.provider.{m.name}({call_args});")
            
            if m.ret_type != "None":
                lines.append(f"                    let resp = {res_name} {{ result }};")
            else:
                lines.append(f"                    let resp = {res_name} {{}};")
                
            lines.append("                    let mut out = Vec::new();")
            lines.append("                    resp.serialize(&mut out).ok()?;")
            lines.append("                    Some(out)")
            lines.append("                } else { None }")
            lines.append("            },")
        lines.append("            _ => None")
        lines.append("        }")
        lines.append("    }")
        lines.append("}")
        lines.append("")

        # Client Proxy
        lines.append(f"pub struct {svc.name}Client {{")
        lines.append("    transport: Arc<UdpTransport>,")
        lines.append("    target: SocketAddr,")
        lines.append("}")
        lines.append(f"impl {svc.name}Client {{")
        lines.append("    pub fn new(transport: Arc<UdpTransport>, target: SocketAddr) -> Self { Self { transport, target } }")
        
        for m in svc.methods:
            method_pascal = m.name.title().replace('_', '')
            args_str = ", ".join([f"{a[0]}: {rust_type(a[1])}" for a in m.args])
            ret_type = f"std::io::Result<{rust_type(m.ret_type)}>" if m.ret_type != "None" else "std::io::Result<()>"
            
            lines.append(f"    pub fn {m.name}(&self, {args_str}) -> {ret_type} {{")
            req_name = f"{svc.name}{method_pascal}Request"
            field_inits = ", ".join([f"{a[0]}" for a in m.args])
            lines.append(f"        let req = {req_name} {{ {field_inits} }};")
            lines.append("        let mut payload = Vec::new();")
            lines.append("        req.serialize(&mut payload)?;")
            lines.append(f"        let header = SomeIpHeader::new({svc.id}, {m.id}, 0x1234, 0x01, 0x00, payload.len() as u32);")
            lines.append("        let mut msg = header.serialize().to_vec();")
            lines.append("        msg.extend(payload);")
            lines.append("        self.transport.send(&msg, Some(self.target))?;")
            
            if m.ret_type != "None":
                lines.append(f"        Ok(Default::default())")
            else:
                lines.append("        Ok(())")
            lines.append("    }")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


# --- Python Generation ---
def generate_python(structs, services):
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
    
    # 1. Generate Structs
    # (Reuse existing logic for serialization helpers)
    # Simplified for brevity in this task, but essential concepts remain
    
    # ... Helper to generate serialization body ...
    def gen_serialization_logic(fields, indent="        "):
        code = []
        code.append(f"{indent}buffer = bytearray()")
        for fname, ftype in fields:
             if ftype == 'int':
                 code.append(f"{indent}buffer.extend(struct.pack('>i', self.{fname}))")
             elif ftype == 'str':
                 code.append(f"{indent}b = self.{fname}.encode('utf-8')")
                 code.append(f"{indent}buffer.extend(struct.pack('>I', len(b)))")
                 code.append(f"{indent}buffer.extend(b)")
             elif ftype.startswith("Vec<"):
                 code.append(f"{indent}temp_buf = bytearray()")
                 code.append(f"{indent}for item in self.{fname}:")
                 code.append(f"{indent}    temp_buf.extend(struct.pack('>i', item))") # Assuming int list
                 code.append(f"{indent}buffer.extend(struct.pack('>I', len(temp_buf)))")
                 code.append(f"{indent}buffer.extend(temp_buf)")
        code.append(f"{indent}return bytes(buffer)")
        return "\n".join(code)

    for s in structs:
        lines.append(f"class {s.name}:")
        args = [f"{f[0]}" for f in s.fields]
        lines.append(f"    def __init__(self, {', '.join(args)}):")
        for f in s.fields: lines.append(f"        self.{f[0]} = {f[0]}")
        lines.append("    def serialize(self) -> bytes:")
        lines.append(gen_serialization_logic(s.fields))
        lines.append("")

    # 2. Generate Services
    for svc in services:
        lines.append(f"# --- Service {svc.name} ---")
        
        # A. Helpers
        for m in svc.methods:
             method_pascal = m.name.title().replace('_', '')
             req_name = f"{svc.name}{method_pascal}Request"
             lines.append(f"class {req_name}:")
             args = [a[0] for a in m.args]
             if args:
                 lines.append(f"    def __init__(self, {', '.join(args)}):")
                 for a in m.args: lines.append(f"        self.{a[0]} = {a[0]}")
             else:
                 lines.append(f"    def __init__(self): pass")
             
             lines.append("    def serialize(self) -> bytes:")
             lines.append(gen_serialization_logic(m.args))
             lines.append("")
             
             # Response
             res_name = f"{svc.name}{method_pascal}Response"
             lines.append(f"class {res_name}:")
             if m.ret_type != "None":
                 lines.append(f"    def __init__(self, result):")
                 lines.append(f"        self.result = result")
                 lines.append("    def serialize(self) -> bytes:")
                 # Helper logic for single result field
                 lines.append(gen_serialization_logic([('result', m.ret_type)]))
             else:
                 lines.append(f"    def __init__(self): pass")
                 lines.append("    def serialize(self) -> bytes:")
                 lines.append("        return b''")
             lines.append("")

        # B. Server Stub
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
            # We need Deserialization! 
            # Simplified deserialization for now (manual unpacking based on types)
            # Or assume the user passed simple types.
            # For MVP Python, let's just do manual unpack for the args we know
            lines.append(f"            # Deserialize {req_name}")
            lines.append(f"            off = 0")
            args_call = []
            for arg_name, arg_type in m.args:
                if arg_type == 'int':
                    lines.append(f"            {arg_name} = struct.unpack_from('>i', payload, off)[0]; off+=4")
                elif arg_type == 'str':
                    lines.append(f"            l = struct.unpack_from('>I', payload, off)[0]; off+=4")
                    lines.append(f"            {arg_name} = payload[off:off+l].decode('utf-8'); off+=l")
                elif arg_type.startswith("Vec<"): # Only int list supported
                     lines.append(f"            l = struct.unpack_from('>I', payload, off)[0]; off+=4")
                     lines.append(f"            # Assuming int list")
                     lines.append(f"            count = l // 4")
                     lines.append(f"            {arg_name} = list(struct.unpack_from(f'>{{count}}i', payload, off)); off+=l")
                args_call.append(arg_name)
            
            lines.append(f"            result = self.{m.name}({', '.join(args_call)})")
            
            if m.ret_type != "None":
                 lines.append(f"            resp = {res_name}(result)")
            else:
                 lines.append(f"            resp = {res_name}()")
                 
            lines.append(f"            res_payload = resp.serialize()")
            lines.append(f"            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)")
            lines.append(f"            sock.sendto(hdr + res_payload, addr)")
            lines.append(f"            return True")
            
        lines.append(f"        return False")
        lines.append("")


        # C. Client
        lines.append(f"class {svc.name}Client:")
        lines.append(f"    SERVICE_ID = {hex(svc.id)}")
        lines.append(f"    def __init__(self, sock, addr):")
        lines.append(f"        self.sock = sock")
        lines.append(f"        self.addr = addr")
        
        for m in svc.methods:
            args = [a[0] for a in m.args]
            sig = ", ".join(["self"] + args)
            lines.append(f"    def {m.name}({sig}):")
            req_name = f"{svc.name}{m.name.capitalize()}Request"
            init_args = ", ".join(args)
            lines.append(f"        req = {req_name}({init_args})")
            lines.append(f"        payload = req.serialize()")
            lines.append(f"        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret")
            lines.append(f"        hdr = struct.pack('>HHIIBBBB', {svc.id}, {m.id}, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)")
            lines.append(f"        self.sock.sendto(hdr + payload, self.addr)")
            lines.append("")

    return "\n".join(lines)

def main(filepath):
    structs, services = parse_file(filepath)
    
    rust_code = generate_rust(structs, services)
    py_code = generate_python(structs, services)
    
    os.makedirs("src/generated", exist_ok=True)
    with open("src/generated/mod.rs", "w") as f: f.write(rust_code)
    with open("src/generated/bindings.py", "w") as f: f.write(py_code)
         
    print("Generated src/generated/")

if __name__ == "__main__":
    main(sys.argv[1])
