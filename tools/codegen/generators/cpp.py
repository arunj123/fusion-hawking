from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type

class CppGenerator(AbstractGenerator):
    def generate(self, structs: list[Struct], services: list[Service]) -> dict[str, str]:
        lines = []
        lines.append("#pragma once")
        lines.append("#include <vector>")
        lines.append("#include <string>")
        lines.append("#include <cstdint>")
        lines.append("")
        lines.append("namespace generated {")
        # SomeIpHeader
        lines.append("struct SomeIpHeader {")
        lines.append("    uint16_t service_id; uint16_t method_id; uint32_t length;")
        lines.append("    uint16_t client_id; uint16_t session_id;")
        lines.append("    uint8_t proto_ver; uint8_t iface_ver; uint8_t msg_type; uint8_t return_code;")
        lines.append("    static SomeIpHeader deserialize(const std::vector<uint8_t>& data) {")
        lines.append("        SomeIpHeader h = {0};")
        lines.append("        if (data.size() < 16) return h;")
        lines.append("        h.service_id = (data[0] << 8) | data[1];")
        lines.append("        h.method_id = (data[2] << 8) | data[3];")
        lines.append("        h.length = (data[4] << 24) | (data[5] << 16) | (data[6] << 8) | data[7];")
        lines.append("        h.client_id = (data[8] << 8) | data[9];")
        lines.append("        h.session_id = (data[10] << 8) | data[11];")
        lines.append("        h.proto_ver = data[12]; h.iface_ver = data[13]; h.msg_type = data[14]; h.return_code = data[15];")
        lines.append("        return h;")
        lines.append("    }")
        lines.append("    std::vector<uint8_t> serialize() const {")
        lines.append("        std::vector<uint8_t> buffer;")
        lines.append("        buffer.push_back(service_id >> 8); buffer.push_back(service_id);")
        lines.append("        buffer.push_back(method_id >> 8); buffer.push_back(method_id);")
        lines.append("        buffer.push_back(length >> 24); buffer.push_back(length >> 16); buffer.push_back(length >> 8); buffer.push_back(length);")
        lines.append("        buffer.push_back(client_id >> 8); buffer.push_back(client_id);")
        lines.append("        buffer.push_back(session_id >> 8); buffer.push_back(session_id);")
        lines.append("        buffer.push_back(proto_ver); buffer.push_back(iface_ver); buffer.push_back(msg_type); buffer.push_back(return_code);")
        lines.append("        return buffer;")
        lines.append("    }")
        lines.append("};")
        
        lines.append("")
        lines.append("// RequestHandler Interface")
        lines.append("class RequestHandler {")
        lines.append("public:")
        lines.append("    virtual uint16_t get_service_id() = 0;")
        lines.append("    virtual std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) = 0;")
        lines.append("};")

        lines.append("")
        lines.append("// Glue for Clients")
        lines.append("void SendRequestGlue(void* rt, uint16_t sid, uint16_t mid, const std::vector<uint8_t>& payload);")
        lines.append("")

        for s in structs:
            lines.append(self._generate_struct(s))
        
        for svc in services:
             lines.append(f"// Service {svc.name}")
             for m in svc.methods:
                  # Request
                  method_pascal = m.name.title().replace('_', '')
                  req_name = f"{svc.name}{method_pascal}Request"
                  lines.append(self._generate_struct(Struct(req_name, m.args)))
                  
                  # Response
                  res_name = f"{svc.name}{method_pascal}Response"
                  res_fields = []
                  if m.ret_type.name != "None":
                      res_fields.append(Field("result", m.ret_type))
                  lines.append(self._generate_struct(Struct(res_name, res_fields)))
             
             # STUB
             lines.append(f"class {svc.name}Stub : public RequestHandler {{")
             lines.append("public:")
             lines.append(f"    static const uint16_t SERVICE_ID = {svc.id};")
             lines.append(f"    uint16_t get_service_id() override {{ return SERVICE_ID; }}")
             lines.append("")
             
             # Virtual Methods
             for m in svc.methods:
                 method_pascal = m.name.title().replace('_', '')
                 req_type = f"{svc.name}{method_pascal}Request"
                 res_type = f"{svc.name}{method_pascal}Response"
                 lines.append(f"    virtual {res_type} {method_pascal}({req_type} req) = 0;")
             
             lines.append("")
             lines.append("    std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) override {")
             lines.append("        const uint8_t* ptr = payload.data(); size_t len = payload.size();")
             lines.append("        switch(header.method_id) {")
             
             for m in svc.methods:
                 method_pascal = m.name.title().replace('_', '')
                 req_type = f"{svc.name}{method_pascal}Request"
                 lines.append(f"            case {m.id}: {{")
                 lines.append(f"                {req_type} req = {req_type}::deserialize(ptr, len);")
                 lines.append(f"                auto res = {method_pascal}(req);")
                 lines.append(f"                return res.serialize();")
                 lines.append(f"            }}")
             
             lines.append("        }")
             lines.append("        return {};")
             lines.append("    }")
             lines.append("};")
             
             # CLIENT
             lines.append(f"class {svc.name}Client {{")
             lines.append("    void* runtime;")
             lines.append("    uint16_t service_id;")
             lines.append("    // sockaddr_in not avail here without include, assume runtime handles send")
             lines.append("    // But we need to pass target. Let's make pure virtual Send interface on runtime?")
             lines.append("    // For simplicity, we assume runtime has SendRequest(sid, payload)")
             lines.append("    // We need to pass target IP/Port? ")
             lines.append("    // Let's assume Runtime handles lookup or we pass generic pointer/struct.")
             lines.append("public:")
             lines.append(f"    static const uint16_t SERVICE_ID = {svc.id};")
             lines.append(f"    {svc.name}Client(void* rt, uint16_t sid) : runtime(rt), service_id(sid) {{}}")
             
             for m in svc.methods:
                 method_pascal = m.name.title().replace('_', '')
                 req_type = f"{svc.name}{method_pascal}Request"
                 
                 # Unpacked args for Client convenience? Or just request struct?
                 # Let's do Unpacked for main.cpp compatibility "client.Add(5,5)"
                 args_sig = []
                 for arg in m.args:
                      args_sig.append(f"{self._cpp_type(arg.type)} {arg.name}")
                 sig_str = ", ".join(args_sig)
                 
                 lines.append(f"    void {method_pascal}({sig_str}) {{")
                 lines.append(f"        {req_type} req;")
                 for arg in m.args:
                      lines.append(f"        req.{arg.name} = {arg.name};")
                 lines.append(f"        std::vector<uint8_t> payload = req.serialize();")
                 lines.append(f"        // Cast runtime and call. We need a forward decl or interface for Runtime.")
                 lines.append(f"        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'")
                 lines.append(f"        // We'll define a 'ISomeIpRuntime' interface at top?")
                 lines.append(f"        // Or just template? No, this is generated.")
                 lines.append(f"        // Expect user to provide 'ISomeIpRuntime' before including this?")
                 lines.append(f"        // Let's use void* and cast, confusing.")
                 lines.append(f"        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'")
                 lines.append(f"        SendRequestGlue(runtime, service_id, {m.id}, payload);")
                 lines.append(f"    }}")

             lines.append("};")

        lines.append("} // namespace generated")
        return {"build/generated/cpp/bindings.h": "\n".join(lines)}

    def _generate_struct(self, s: Struct) -> str:
        lines = []
        lines.append(f"struct {s.name} {{")
        for f in s.fields:
            lines.append(f"    {self._cpp_type(f.type)} {f.name};")
        
        lines.append("")
        lines.append("    // Serialize")
        lines.append("    std::vector<uint8_t> serialize() const {")
        lines.append("        std::vector<uint8_t> buffer;")
        for f in s.fields:
             lines.append(self._gen_serialization_logic(f))
        lines.append("        return buffer;")
        lines.append("    }")
        
        lines.append("")
        lines.append("    // Deserialize")
        lines.append(f"    static {s.name} deserialize(const uint8_t*& data, size_t& len) {{")
        lines.append(f"        {s.name} obj;")
        for f in s.fields:
             lines.append(self._gen_deserialization_logic(f))
        lines.append("        return obj;")
        lines.append("    }")
        
        lines.append("};")
        return "\n".join(lines)

    def _gen_serialization_logic(self, f: Field) -> str:
        t = f.type
        name = f.name
        code = []
        if t.is_list and t.name == 'int': # Vec<int>
             code.append(f"        uint32_t len_{name} = static_cast<uint32_t>({name}.size() * 4);")
             code.append(f"        buffer.push_back(len_{name} >> 24); buffer.push_back(len_{name} >> 16); buffer.push_back(len_{name} >> 8); buffer.push_back(len_{name});")
             code.append(f"        for(int32_t val : {name}) {{")
             code.append(f"            buffer.push_back(val >> 24); buffer.push_back(val >> 16); buffer.push_back(val >> 8); buffer.push_back(val);")
             code.append(f"        }}")
        elif t.name == 'int': # int32
             code.append(f"        buffer.push_back({name} >> 24); buffer.push_back({name} >> 16); buffer.push_back({name} >> 8); buffer.push_back({name});")
        elif t.name == 'float':
             # Naive cast
             code.append(f"        uint32_t val_{name} = *reinterpret_cast<const uint32_t*>(&{name});")
             code.append(f"        buffer.push_back(val_{name} >> 24); buffer.push_back(val_{name} >> 16); buffer.push_back(val_{name} >> 8); buffer.push_back(val_{name});")
        elif t.name == 'str':
             code.append(f"        uint32_t len_{name} = static_cast<uint32_t>({name}.length());")
             code.append(f"        buffer.push_back(len_{name} >> 24); buffer.push_back(len_{name} >> 16); buffer.push_back(len_{name} >> 8); buffer.push_back(len_{name});")
             code.append(f"        for(char c : {name}) buffer.push_back(c);")
        return "\n".join(code)

    def _gen_deserialization_logic(self, f: Field) -> str:
        t = f.type
        name = f.name
        code = []
        if t.is_list and t.name == 'int':
             code.append(f"        uint32_t byte_len_{name} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
             code.append(f"        int count_{name} = byte_len_{name} / 4;")
             code.append(f"        for(int i=0; i<count_{name}; i++) {{")
             code.append(f"             int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
             code.append(f"             obj.{name}.push_back(val);")
             code.append(f"        }}")
        elif t.name == 'int':
             code.append(f"        obj.{name} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
        elif t.name == 'float':
             code.append(f"        uint32_t val_{name} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
             code.append(f"        obj.{name} = *reinterpret_cast<float*>(&val_{name});")
        elif t.name == 'str':
             code.append(f"        uint32_t byte_len_{name} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
             code.append(f"        obj.{name}.assign(reinterpret_cast<const char*>(data), byte_len_{name}); data+=byte_len_{name}; len-=byte_len_{name};")
        return "\n".join(code)

    def _cpp_type(self, t: Type) -> str:
        if t.is_list:
            return f"std::vector<{self._cpp_type(Type(t.name))}>"
            
        mapping = { 'int': 'int32_t', 'float': 'float', 'str': 'std::string', 'bool': 'bool', 'None': 'void' }
        if t.name in mapping: return mapping[t.name]
        return t.name
