from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type

class RustGenerator(AbstractGenerator):
    def generate(self, structs: list[Struct], services: list[Service]) -> dict[str, str]:
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
            lines.append(self._generate_struct(s))
            lines.append("")

        for svc in services:
            lines.append(f"// --- Service: {svc.name} (ID: {hex(svc.id)}) ---")
            
            for m in svc.methods:
                method_pascal = m.name.title().replace('_', '')
                
                # Request Struct
                req_name = f"{svc.name}{method_pascal}Request"
                lines.append(self._generate_struct(Struct(req_name, m.args)))
                
                # Response Struct
                res_name = f"{svc.name}{method_pascal}Response"
                res_fields = []
                if m.ret_type.name != "None":
                    res_fields.append(Field("result", m.ret_type))
                lines.append(self._generate_struct(Struct(res_name, res_fields)))
                lines.append("")

            for e in svc.events:
                event_pascal = e.name.title().replace('_', '')
                event_name = f"{svc.name}{event_pascal}Event"
                lines.append(self._generate_struct(Struct(event_name, e.args)))
                lines.append("")
            
            for f in svc.fields:
                field_pascal = f.name.title().replace('_', '')
                # Generate field type struct or just use primitive
                # For now, let's just make sure it parses.
                pass

            # Provider Trait
            lines.append(self._generate_provider_trait(svc))
            
            # Server Stub
            lines.append(self._generate_server_stub(svc))
            
            # Client Proxy
            lines.append(self._generate_client_proxy(svc))

        return {"build/generated/rust/mod.rs": "\n".join(lines)}

    def _generate_struct(self, s: Struct) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"#[derive(Debug, Clone, PartialEq)]")
        lines.append(f"pub struct {s.name} {{")
        for f in s.fields:
            lines.append(f"    pub {f.name}: {self._rust_type(f.type)},")
        lines.append("}")
        
        # Serialize
        lines.append(f"impl SomeIpSerialize for {s.name} {{")
        lines.append(f"    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {{")
        for f in s.fields:
            lines.append(f"        self.{f.name}.serialize(writer)?;")
        lines.append("        Ok(())")
        lines.append("    }")
        lines.append("}")
        
        # Deserialize
        lines.append(f"impl SomeIpDeserialize for {s.name} {{")
        lines.append(f"    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {{")
        lines.append(f"        Ok({s.name} {{")
        for f in s.fields:
            lines.append(f"            {f.name}: <{self._rust_type(f.type)}>::deserialize(reader)?,")
        lines.append("        })")
        lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def _generate_provider_trait(self, svc: Service) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"pub trait {svc.name}Provider: Send + Sync {{")
        for m in svc.methods:
            args_str = ", ".join([f"{a.name}: {self._rust_type(a.type)}" for a in m.args])
            ret_str = f" -> {self._rust_type(m.ret_type)}" if m.ret_type.name != "None" else ""
            lines.append(f"    fn {m.name}(&self, {args_str}){ret_str};")
        lines.append("}")
        return "\n".join(lines)

    def _generate_server_stub(self, svc: Service) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"pub struct {svc.name}Server<T: {svc.name}Provider> {{")
        lines.append("    provider: Arc<T>,")
        lines.append("}")
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"impl<T: {svc.name}Provider> {svc.name}Server<T> {{")
        lines.append("    pub fn new(provider: Arc<T>) -> Self { Self { provider } }")
        lines.append("}")
        
        lines.append(f"impl<T: {svc.name}Provider> fusion_hawking::runtime::RequestHandler for {svc.name}Server<T> {{")
        lines.append(f"    fn service_id(&self) -> u16 {{ {svc.id} }}")
        lines.append("    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>> {")
        lines.append(f"        if header.service_id != {svc.id} {{ return None; }}")
        lines.append("        match header.method_id {")
        for m in svc.methods:
            method_pascal = m.name.title().replace('_', '')
            req_name = f"{svc.name}{method_pascal}Request"
            res_name = f"{svc.name}{method_pascal}Response"
            lines.append(f"            {m.id} => {{")
            lines.append(f"                let mut cursor = Cursor::new(payload);")
            lines.append(f"                if let Ok(req) = {req_name}::deserialize(&mut cursor) {{")
            
            call_args = ", ".join([f"req.{a.name}" for a in m.args])
            lines.append(f"                    let result = self.provider.{m.name}({call_args});")
            
            if m.ret_type.name != "None":
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
        return "\n".join(lines)

    def _generate_client_proxy(self, svc: Service) -> str:
        lines = []
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"pub struct {svc.name}Client {{")
        lines.append("    transport: Arc<UdpTransport>,")
        lines.append("    target: SocketAddr,")
        lines.append("}")
        
        lines.append(f"impl fusion_hawking::runtime::ServiceClient for {svc.name}Client {{")
        lines.append(f"    const SERVICE_ID: u16 = {svc.id};")
        lines.append("    fn new(transport: Arc<UdpTransport>, target: SocketAddr) -> Self { Self { transport, target } }")
        lines.append("}")
        
        lines.append(f"#[allow(dead_code)]")
        lines.append(f"impl {svc.name}Client {{")
        
        for m in svc.methods:
            method_pascal = m.name.title().replace('_', '')
            args_str = ", ".join([f"{a.name}: {self._rust_type(a.type)}" for a in m.args])
            ret_type = f"std::io::Result<{self._rust_type(m.ret_type)}>" if m.ret_type.name != "None" else "std::io::Result<()>"
            
            lines.append(f"    pub fn {m.name}(&self, {args_str}) -> {ret_type} {{")
            req_name = f"{svc.name}{method_pascal}Request"
            field_inits = ", ".join([f"{a.name}" for a in m.args])
            lines.append(f"        let req = {req_name} {{ {field_inits} }};")
            lines.append("        let mut payload = Vec::new();")
            lines.append("        req.serialize(&mut payload)?;")
            lines.append(f"        let header = SomeIpHeader::new({svc.id}, {m.id}, 0x1234, 0x01, 0x00, payload.len() as u32);")
            lines.append("        let mut msg = header.serialize().to_vec();")
            lines.append("        msg.extend(payload);")
            lines.append("        self.transport.send(&msg, Some(self.target))?;")
            
            if m.ret_type.name != "None":
                lines.append(f"        Ok(Default::default())")
            else:
                lines.append("        Ok(())")
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def _rust_type(self, t: Type) -> str:
        if t.is_list:
            return f"Vec<{self._rust_type(Type(t.name))}>"
            
        mapping = { 'int': 'i32', 'float': 'f32', 'str': 'String', 'bool': 'bool', 'None': '()' }
        if t.name in mapping: return mapping[t.name]
        return t.name
