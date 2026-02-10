from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type

class RustGenerator(AbstractGenerator):
    def _to_pascal(self, name: str) -> str:
        # Handle already PascalCase-ish but with underscores (e.g. IVersionedService_v1)
        # Split by underscores and capitalize each part
        parts = name.split('_')
        return "".join(p[:1].upper() + p[1:] for p in parts if p)

    def generate(self, structs: list[Struct], services: list[Service], output_dir: str = "build/generated") -> dict[str, str]:
        lines = [
            "use fusion_hawking::codec::{SomeIpSerialize, SomeIpDeserialize, SomeIpHeader};",
            "#[allow(unused_imports)]",
            "use std::io::{Result, Write, Read, Cursor};",
            "#[allow(unused_imports)]",
            "use std::sync::Arc;",
            "#[allow(unused_imports)]",
            "use fusion_hawking::transport::{UdpTransport, SomeIpTransport};",
            "#[allow(unused_imports)]",
            "use std::net::SocketAddr;",
            ""
        ]

        for s in structs:
            # Structs from IDL might need PascalCase conversion
            # We construct a new Struct object with modified name/type names
            pascal_name = self._to_pascal(s.name)
            # We need to map field types too? _rust_type handles it if we modify it.
            # But here we pass 's' which has original name. 
            # We can just generate with pascal_name
            lines.append(self._generate_struct(s, pascal_name))
            lines.append("")

        for svc in services:
            pasc_svc_name = self._to_pascal(svc.name)
            lines.append(f"// --- Service: {svc.name} (ID: {hex(svc.id)}) ---")
            
            for m in svc.methods:
                method_pascal = self._to_pascal(m.name)
                
                # Request Struct
                req_name = f"{pasc_svc_name}{method_pascal}Request"
                lines.append(self._generate_struct(Struct(req_name, m.args), req_name))
                
                # Response Struct
                res_name = f"{pasc_svc_name}{method_pascal}Response"
                res_fields = []
                if m.ret_type.name != "None":
                    res_fields.append(Field("result", m.ret_type))
                lines.append(self._generate_struct(Struct(res_name, res_fields), res_name))
                lines.append("")

            for e in svc.events:
                event_pascal = self._to_pascal(e.name)
                event_name = f"{pasc_svc_name}{event_pascal}Event"
                lines.append(self._generate_struct(Struct(event_name, e.args), event_name))
                lines.append("")
            
            # Provider Trait
            lines.append(self._generate_provider_trait(svc, pasc_svc_name))
            
            # Server Stub
            lines.append(self._generate_server_stub(svc, pasc_svc_name))
            
            # Client Proxy
            lines.append(self._generate_client_proxy(svc, pasc_svc_name))

        import os
        return {os.path.join(output_dir, "rust/mod.rs"): "\n".join(lines)}

    def _generate_struct(self, s: Struct, struct_name: str) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"#[derive(Debug, Clone, PartialEq)]")
        lines.append(f"pub struct {struct_name} {{")
        for f in s.fields:
            lines.append(f"    pub {f.name}: {self._rust_type(f.type)},")
        lines.append("}")
        
        # Serialize
        lines.append(f"impl SomeIpSerialize for {struct_name} {{")
        # Use _writer for empty structs to avoid unused variable warning
        writer_param = "_writer" if len(s.fields) == 0 else "writer"
        lines.append(f"    fn serialize<W: Write>(&self, {writer_param}: &mut W) -> Result<()> {{")
        for f in s.fields:
            lines.append(f"        self.{f.name}.serialize(writer)?;")
        lines.append("        Ok(())")
        lines.append("    }")
        lines.append("}")
        
        # Deserialize
        lines.append(f"impl SomeIpDeserialize for {struct_name} {{")
        # Use _reader for empty structs to avoid unused variable warning
        reader_param = "_reader" if len(s.fields) == 0 else "reader"
        lines.append(f"    fn deserialize<R: Read>({reader_param}: &mut R) -> Result<Self> {{")
        lines.append(f"        Ok({struct_name} {{")
        for f in s.fields:
            lines.append(f"            {f.name}: <{self._rust_type(f.type)}>::deserialize(reader)?,")
        lines.append("        })")
        lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def _generate_provider_trait(self, svc: Service, trait_name: str) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"pub trait {trait_name}Provider: Send + Sync {{")
        for m in svc.methods:
            args_str = ", ".join([f"{a.name}: {self._rust_type(a.type)}" for a in m.args])
            ret_str = f" -> {self._rust_type(m.ret_type)}" if m.ret_type.name != "None" else ""
            lines.append(f"    fn {m.name}(&self, {args_str}){ret_str};")
        lines.append("}")
        return "\n".join(lines)

    def _generate_server_stub(self, svc: Service, svc_pascal: str) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"pub struct {svc_pascal}Server<T> {{")
        lines.append("    provider: Arc<T>,")
        lines.append("}")
        lines.append("#[allow(dead_code)]")
        lines.append(f"impl {svc_pascal}Server<()> {{")
        lines.append(f"    pub const SERVICE_ID: u16 = {svc.id};")
        lines.append(f"    pub const MAJOR_VERSION: u32 = {svc.major_version};")
        lines.append(f"    pub const MINOR_VERSION: u32 = {svc.minor_version};")
        for m in svc.methods:
            lines.append(f"    pub const METHOD_{m.name.upper()}: u16 = {m.id};")
        for e in svc.events:
            lines.append(f"    pub const EVENT_{e.name.upper()}: u16 = {e.id};")
        lines.append("}")
        
        lines.append("")
        lines.append(f"impl<T: {svc_pascal}Provider> {svc_pascal}Server<T> {{")
        lines.append("    #[allow(dead_code)]")
        lines.append("    pub fn new(provider: Arc<T>) -> Self { Self { provider } }")
        lines.append("}")
        
        lines.append(f"impl<T: {svc_pascal}Provider> fusion_hawking::runtime::RequestHandler for {svc_pascal}Server<T> {{")
        lines.append(f"    fn service_id(&self) -> u16 {{ {svc_pascal}Server::<()>::SERVICE_ID }}")
        lines.append(f"    fn major_version(&self) -> u8 {{ {svc_pascal}Server::<()>::MAJOR_VERSION as u8 }}")
        lines.append(f"    fn minor_version(&self) -> u32 {{ {svc_pascal}Server::<()>::MINOR_VERSION }}")
        lines.append("    fn handle(&self, header: &SomeIpHeader, _payload: &[u8]) -> Option<Vec<u8>> {")
        lines.append(f"        // println!(\"DEBUG: Handler {svc.name} handling {{:?}}\", header);")
        lines.append(f"        if header.service_id != {svc_pascal}Server::<()>::SERVICE_ID {{ return None; }}")
        lines.append("        match header.method_id {")
        for m in svc.methods:
            method_pascal = self._to_pascal(m.name)
            req_name = f"{svc_pascal}{method_pascal}Request"
            res_name = f"{svc_pascal}{method_pascal}Response"
            lines.append(f"            {svc_pascal}Server::<()>::METHOD_{m.name.upper()} => {{")
            lines.append(f"                let mut cursor = Cursor::new(_payload);")
            # Use _req when method has no arguments to avoid unused variable warning
            req_binding = "_req" if len(m.args) == 0 else "req"
            lines.append(f"                if let Ok({req_binding}) = {req_name}::deserialize(&mut cursor) {{")
            
            call_args = ", ".join([f"req.{a.name}" for a in m.args])
            
            # For void methods, just call without assigning; for others, assign to result
            if m.ret_type.name != "None":
                lines.append(f"                    let result = self.provider.{m.name}({call_args});")
                lines.append(f"                    let resp = {res_name} {{ result }};")
            else:
                lines.append(f"                    self.provider.{m.name}({call_args});")
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
        return "\n".join(lines)

    def _generate_client_proxy(self, svc: Service, svc_pascal: str) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"pub struct {svc_pascal}Client {{")
        lines.append("    transport: Arc<dyn SomeIpTransport>,")
        lines.append("    target: SocketAddr,")
        lines.append("}")
        
        lines.append(f"impl fusion_hawking::runtime::ServiceClient for {svc_pascal}Client {{")
        lines.append(f"    const SERVICE_ID: u16 = {svc.id};")
        lines.append("    fn new(transport: Arc<dyn SomeIpTransport>, target: SocketAddr) -> Self { Self { transport, target } }")
        lines.append("}")
        
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"impl {svc_pascal}Client {{")
        lines.append(f"    pub const SERVICE_ID: u16 = {svc.id};")
        lines.append(f"    pub const MAJOR_VERSION: u32 = {svc.major_version};")
        lines.append(f"    pub const MINOR_VERSION: u32 = {svc.minor_version};")
        
        for m in svc.methods:
            method_pascal = self._to_pascal(m.name)
            args_str = ", ".join([f"{a.name}: {self._rust_type(a.type)}" for a in m.args])
            ret_type = f"std::io::Result<{self._rust_type(m.ret_type)}>" if m.ret_type.name != "None" else "std::io::Result<()>"
            
            lines.append(f"    pub fn {m.name}(&self, {args_str}) -> {ret_type} {{")
            req_name = f"{svc_pascal}{method_pascal}Request"
            field_inits = ", ".join([f"{a.name}" for a in m.args])
            lines.append(f"        let req = {req_name} {{ {field_inits} }};")
            lines.append("        let mut payload = Vec::new();")
            req_expr = "req"
            lines.append(f"        {req_expr}.serialize(&mut payload)?;")
            
            lines.append(f"        let header = SomeIpHeader::new(Self::SERVICE_ID, {svc_pascal}Server::<()>::METHOD_{m.name.upper()}, 0x1234, 0x01, 0x01, payload.len() as u32);")
            lines.append("        let mut msg = header.serialize().to_vec();")
            lines.append("        msg.extend(payload);")
            lines.append("        self.transport.send(&msg, Some(self.target))?;")
            
            if m.ret_type.name != "None":
                # For now, sync RPC is not implemented in client - return error
                # TODO: Implement proper request-response with runtime integration
                lines.append(f"        // TODO: Sync RPC requires runtime integration")
                lines.append(f"        Err(std::io::Error::new(std::io::ErrorKind::Other, \"Sync RPC not yet implemented in client\"))")
            else:
                lines.append("        Ok(())")
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def _rust_type(self, t: Type) -> str:
        if t.inner:
            return f"Vec<{self._rust_type(t.inner)}>"
            
        mapping = { 
            'int': 'i32', 'int32': 'i32', 'int8': 'i8', 'int16': 'i16', 'int64': 'i64',
            'uint8': 'u8', 'uint16': 'u16', 'uint32': 'u32', 'uint64': 'u64',
            'float': 'f32', 'float32': 'f32', 'float64': 'f64', 'double': 'f64',
            'string': 'String', 'str': 'String', 'bool': 'bool', 'None': '()' 
        }
        if t.name in mapping: return mapping[t.name]
        return self._to_pascal(t.name)
