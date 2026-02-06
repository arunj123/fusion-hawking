from .base import AbstractGenerator
from ..models import Struct, Service, Method, Field, Type

class CppGenerator(AbstractGenerator):
    def generate(self, structs: list[Struct], services: list[Service]) -> dict[str, str]:
        lines = []
        lines.append("#pragma once")
        lines.append("#include <vector>")
        lines.append("#include <string>")
        lines.append("#include <cstdint>")
        lines.append("#include <fusion_hawking/types.hpp>")
        lines.append("")
        lines.append("namespace generated {")
        lines.append("using namespace fusion_hawking;")
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
             
             for e in svc.events:
                  event_pascal = e.name.title().replace('_', '')
                  event_name = f"{svc.name}{event_pascal}Event"
                  lines.append(self._generate_struct(Struct(event_name, e.args)))
             
             # STUB
             lines.append(f"class {svc.name}Stub : public RequestHandler {{")
             lines.append("public:")
             lines.append(f"    static const uint16_t SERVICE_ID = {svc.id};")
             lines.append(f"    uint16_t get_service_id() override {{ return SERVICE_ID; }}")

             # Method IDs
             for m in svc.methods:
                 lines.append(f"    static const uint16_t METHOD_{m.name.upper()} = {m.id};")
             
             # Event IDs
             for e in svc.events:
                 lines.append(f"    static const uint16_t EVENT_{e.name.upper()} = {e.id};")
             
             # Field IDs (Get/Set/Notifier)
             for f in svc.fields:
                 if f.get_id: lines.append(f"    static const uint16_t FIELD_GET_{f.name.upper()} = {f.get_id};")
                 if f.set_id: lines.append(f"    static const uint16_t FIELD_SET_{f.name.upper()} = {f.set_id};")
                 if f.notifier_id: lines.append(f"    static const uint16_t EVENT_{f.name.upper()}_NOTIFY = {f.notifier_id};")
             lines.append("")
             
             # Virtual Methods
             for m in svc.methods:
                 method_pascal = m.name.title().replace('_', '')
                 req_type = f"{svc.name}{method_pascal}Request"
                 res_type = f"{svc.name}{method_pascal}Response"
                 lines.append(f"    virtual {res_type} {method_pascal}({req_type} req) = 0;")
             
             for f in svc.fields:
                 field_pascal = f.name.title().replace('_', '')
                 if f.get_id:
                     ret_type = self._cpp_type(f.type)
                     lines.append(f"    virtual {ret_type} Get{field_pascal}() = 0;")
                 if f.set_id:
                     arg_type = self._cpp_type(f.type)
                     lines.append(f"    virtual void Set{field_pascal}({arg_type} val) = 0;")
             
             lines.append("")
             lines.append("    std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) override {")
             lines.append("        const uint8_t* data = payload.data(); size_t len = payload.size();")
             lines.append("        switch(header.method_id) {")
             
             for m in svc.methods:
                 method_pascal = m.name.title().replace('_', '')
                 req_type = f"{svc.name}{method_pascal}Request"
                 lines.append(f"            case METHOD_{m.name.upper()}: {{")
                 lines.append(f"                {req_type} req = {req_type}::deserialize(data, len);")
                 lines.append(f"                auto res = {method_pascal}(req);")
                 lines.append(f"                return res.serialize();")
                 lines.append(f"            }}")
             for f in svc.fields:
                 field_pascal = f.name.title().replace('_', '')
                 if f.get_id:
                     lines.append(f"            case FIELD_GET_{f.name.upper()}: {{")
                     lines.append(f"                auto res = Get{field_pascal}();")
                     lines.append(f"                std::vector<uint8_t> buffer;")
                     lines.append(self._serialize_val_cpp("res", f.type, indent="                "))
                     lines.append(f"                return buffer;")
                     lines.append(f"            }}")
                 if f.set_id:
                     lines.append(f"            case FIELD_SET_{f.name.upper()}: {{")
                     lines.append(f"                {self._cpp_type(f.type)} val;")
                     lines.append(self._deserialize_val_cpp("val", f.type, indent="                "))
                     lines.append(f"                Set{field_pascal}(val);")
                     lines.append(f"                return {{}};")
                     lines.append(f"            }}")
             
             lines.append("        }")
             lines.append("        return {};")
             lines.append("    }")
             lines.append("};")
             
             # CLIENT
             lines.append(f"class {svc.name}Client {{")
             lines.append("    void* runtime;")
             lines.append("    uint16_t service_id;")
             lines.append("public:")
             lines.append(f"    static const uint16_t SERVICE_ID = {svc.id};")
             lines.append(f"    {svc.name}Client(void* rt, uint16_t sid) : runtime(rt), service_id(sid) {{}}")
             
             for m in svc.methods:
                 method_pascal = m.name.title().replace('_', '')
                 req_type = f"{svc.name}{method_pascal}Request"
                 
                 args_sig = []
                 for arg in m.args:
                      args_sig.append(f"{self._cpp_type(arg.type)} {arg.name}")
                 sig_str = ", ".join(args_sig)
                 
                 lines.append(f"    {svc.name}{method_pascal}Response {method_pascal}({sig_str}) {{")
                 lines.append(f"        {req_type} req;")
                 for arg in m.args:
                      lines.append(f"        req.{arg.name} = {arg.name};")
                 lines.append(f"        std::vector<uint8_t> payload = req.serialize();")
                 lines.append(f"        std::vector<uint8_t> res_payload = fusion_hawking::SendRequestGlue(runtime, service_id, {svc.name}Stub::METHOD_{m.name.upper()}, payload);")
                 lines.append(f"        if (res_payload.empty()) {{")
                 lines.append(f"            // Return default/empty on failure")
                 lines.append(f"            return {svc.name}{method_pascal}Response();")
                 lines.append(f"        }}")
                 lines.append(f"        size_t len = res_payload.size();")
                 lines.append(f"        const uint8_t* ptr = res_payload.data();")
                 lines.append(f"        return {svc.name}{method_pascal}Response::deserialize(ptr, len);")
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
        return self._serialize_val_cpp(f"this->{f.name}", f.type, indent="        ")

    def _serialize_val_cpp(self, expr: str, t: Type, indent: str) -> str:
        code = []
        if t.inner:
            code.append(f"{indent}{{")
            code.append(f"{indent}    size_t start_idx = buffer.size();")
            code.append(f"{indent}    buffer.resize(start_idx + 4);")
            code.append(f"{indent}    size_t data_start = buffer.size();")
            code.append(f"{indent}    for(const auto& item : {expr}) {{")
            code.append(self._serialize_val_cpp("item", t.inner, indent + "        "))
            code.append(f"{indent}    }}")
            code.append(f"{indent}    uint32_t data_len = static_cast<uint32_t>(buffer.size() - data_start);")
            code.append(f"{indent}    buffer[start_idx] = static_cast<uint8_t>(data_len >> 24);")
            code.append(f"{indent}    buffer[start_idx+1] = static_cast<uint8_t>(data_len >> 16);")
            code.append(f"{indent}    buffer[start_idx+2] = static_cast<uint8_t>(data_len >> 8);")
            code.append(f"{indent}    buffer[start_idx+3] = static_cast<uint8_t>(data_len);")
            code.append(f"{indent}}}")
        elif t.name in ('int', 'int32'):
            code.append(f"{indent}buffer.push_back({expr} >> 24); buffer.push_back({expr} >> 16); buffer.push_back({expr} >> 8); buffer.push_back({expr});")
        elif t.name == 'int8':
            code.append(f"{indent}buffer.push_back({expr});")
        elif t.name == 'int16':
            code.append(f"{indent}buffer.push_back({expr} >> 8); buffer.push_back({expr});")
        elif t.name == 'int64':
            code.append(f"{indent}for(int i=7; i>=0; --i) buffer.push_back(({expr} >> (i*8)) & 0xFF);")
        elif t.name == 'uint8':
            code.append(f"{indent}buffer.push_back({expr});")
        elif t.name == 'uint16':
            code.append(f"{indent}buffer.push_back({expr} >> 8); buffer.push_back({expr});")
        elif t.name == 'uint32':
            code.append(f"{indent}buffer.push_back({expr} >> 24); buffer.push_back({expr} >> 16); buffer.push_back({expr} >> 8); buffer.push_back({expr});")
        elif t.name == 'uint64':
            code.append(f"{indent}for(int i=7; i>=0; --i) buffer.push_back(({expr} >> (i*8)) & 0xFF);")
        elif t.name in ('float', 'float32'):
            code.append(f"{indent}{{ uint32_t v; std::memcpy(&v, &{expr}, 4); buffer.push_back(v >> 24); buffer.push_back(v >> 16); buffer.push_back(v >> 8); buffer.push_back(v); }}")
        elif t.name in ('double', 'float64'):
            code.append(f"{indent}{{ uint64_t v; std::memcpy(&v, &{expr}, 8); for(int i=7; i>=0; --i) buffer.push_back((v >> (i*8)) & 0xFF); }}")
        elif t.name == 'bool':
            code.append(f"{indent}buffer.push_back({expr} ? 1 : 0);")
        elif t.name in ('str', 'string'):
            code.append(f"{indent}{{ uint32_t slen = static_cast<uint32_t>({expr}.length());")
            code.append(f"{indent}  buffer.push_back(slen >> 24); buffer.push_back(slen >> 16); buffer.push_back(slen >> 8); buffer.push_back(slen);")
            code.append(f"{indent}  for(char c : {expr}) buffer.push_back(static_cast<uint8_t>(c)); }}")
        else: # Struct
            code.append(f"{indent}{{ std::vector<uint8_t> s_buf = {expr}.serialize(); buffer.insert(buffer.end(), s_buf.begin(), s_buf.end()); }}")
        return "\n".join(code)

    def _gen_deserialization_logic(self, f: Field) -> str:
        return self._deserialize_val_cpp(f"obj.{f.name}", f.type, indent="        ")

    def _deserialize_val_cpp(self, expr_target: str, t: Type, indent: str) -> str:
        code = []
        if t.inner:
            code.append(f"{indent}{{")
            code.append(f"{indent}    uint32_t blen = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
            code.append(f"{indent}    const uint8_t* end = data + blen;")
            code.append(f"{indent}    while(data < end) {{")
            code.append(f"{indent}        {self._cpp_type(t.inner)} item;")
            code.append(self._deserialize_val_cpp("item", t.inner, indent + "        "))
            code.append(f"{indent}        {expr_target}.push_back(item);")
            code.append(f"{indent}    }}")
            code.append(f"{indent}}}")
        elif t.name in ('int', 'int32'):
            code.append(f"{indent}{{ {expr_target} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4; }}")
        elif t.name == 'int8':
            code.append(f"{indent}{{ {expr_target} = static_cast<int8_t>(*data); data+=1; len-=1; }}")
        elif t.name == 'int16':
            code.append(f"{indent}{{ {expr_target} = static_cast<int16_t>((data[0] << 8) | data[1]); data+=2; len-=2; }}")
        elif t.name == 'int64':
            code.append(f"{indent}{{ uint64_t v = 0; for(int i=0; i<8; ++i) v = (v << 8) | data[i]; data+=8; len-=8; {expr_target} = static_cast<int64_t>(v); }}")
        elif t.name == 'uint8':
            code.append(f"{indent}{{ {expr_target} = *data; data+=1; len-=1; }}")
        elif t.name == 'uint16':
            code.append(f"{indent}{{ {expr_target} = (data[0] << 8) | data[1]; data+=2; len-=2; }}")
        elif t.name == 'uint32':
            code.append(f"{indent}{{ {expr_target} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4; }}")
        elif t.name == 'uint64':
            code.append(f"{indent}{{ {expr_target} = 0; for(int i=0; i<8; ++i) {expr_target} = ({expr_target} << 8) | data[i]; data+=8; len-=8; }}")
        elif t.name in ('float', 'float32'):
            code.append(f"{indent}{{ uint32_t v = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4; std::memcpy(&{expr_target}, &v, 4); }}")
        elif t.name in ('double', 'float64'):
            code.append(f"{indent}{{ uint64_t v = 0; for(int i=0; i<8; ++i) v = (v << 8) | data[i]; data+=8; len-=8; std::memcpy(&{expr_target}, &v, 8); }}")
        elif t.name == 'bool':
            code.append(f"{indent}{{ {expr_target} = (*data != 0); data+=1; len-=1; }}")
        elif t.name in ('str', 'string'):
            code.append(f"{indent}{{ uint32_t slen = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
            code.append(f"{indent}  {expr_target}.assign(reinterpret_cast<const char*>(data), slen); data+=slen; len-=slen; }}")
        else: # Struct
            code.append(f"{indent}{expr_target} = {t.name}::deserialize(data, len);")
        return "\n".join(code)

    def _cpp_type(self, t: Type) -> str:
        if t.inner:
            return f"std::vector<{self._cpp_type(t.inner)}>"
            
        mapping = { 
            'int': 'int32_t', 'int32': 'int32_t', 'int8': 'int8_t', 'int16': 'int16_t', 'int64': 'int64_t',
            'uint8': 'uint8_t', 'uint16': 'uint16_t', 'uint32': 'uint32_t', 'uint64': 'uint64_t',
            'float': 'float', 'float32': 'float', 'float64': 'double', 'double': 'double',
            'string': 'std::string', 'str': 'std::string', 'bool': 'bool', 'None': 'void' 
        }
        if t.name in mapping: return mapping[t.name]
        return t.name
