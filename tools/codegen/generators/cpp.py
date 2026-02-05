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
        t = f.type
        name = f.name
        code = []
        if t.is_list:
             code.append(f"        {{")
             code.append(f"            size_t start_idx = buffer.size();")
             code.append(f"            buffer.resize(start_idx + 4); // Placeholder for length")
             code.append(f"            size_t data_start = buffer.size();")
             code.append(f"            for(const auto& item : {name}) {{")
             inner_type = Type(t.name, is_list=False)
             code.append(self._serialize_val_cpp("item", inner_type, indent="                "))
             code.append(f"            }}")
             code.append(f"            uint32_t data_len = static_cast<uint32_t>(buffer.size() - data_start);")
             code.append(f"            buffer[start_idx] = static_cast<uint8_t>(data_len >> 24);")
             code.append(f"            buffer[start_idx+1] = static_cast<uint8_t>(data_len >> 16);")
             code.append(f"            buffer[start_idx+2] = static_cast<uint8_t>(data_len >> 8);")
             code.append(f"            buffer[start_idx+3] = static_cast<uint8_t>(data_len);")
             code.append(f"        }}")
        else:
             code.append(self._serialize_val_cpp(name, t, indent="        "))
        return "\n".join(code)

    def _serialize_val_cpp(self, expr: str, t: Type, indent: str) -> str:
        if t.name == 'int':
             return f"{indent}buffer.push_back(static_cast<uint8_t>({expr} >> 24)); buffer.push_back(static_cast<uint8_t>({expr} >> 16)); buffer.push_back(static_cast<uint8_t>({expr} >> 8)); buffer.push_back(static_cast<uint8_t>({expr}));"
        elif t.name == 'float':
             return f"{indent}{{ uint32_t val = *reinterpret_cast<const uint32_t*>(&{expr});\n{indent}  buffer.push_back(static_cast<uint8_t>(val >> 24)); buffer.push_back(static_cast<uint8_t>(val >> 16)); buffer.push_back(static_cast<uint8_t>(val >> 8)); buffer.push_back(static_cast<uint8_t>(val)); }}"
        elif t.name == 'bool':
             return f"{indent}buffer.push_back(static_cast<uint8_t>({expr} ? 1 : 0));"
        elif t.name == 'str':
             return f"{indent}{{\n{indent}    uint32_t slen = static_cast<uint32_t>({expr}.length());\n{indent}    buffer.push_back(static_cast<uint8_t>(slen >> 24)); buffer.push_back(static_cast<uint8_t>(slen >> 16)); buffer.push_back(static_cast<uint8_t>(slen >> 8)); buffer.push_back(static_cast<uint8_t>(slen));\n{indent}    for(char c : {expr}) buffer.push_back(static_cast<uint8_t>(c));\n{indent}}}"
        else: # Struct
             return f"{indent}{{\n{indent}    std::vector<uint8_t> s_buf = {expr}.serialize();\n{indent}    buffer.insert(buffer.end(), s_buf.begin(), s_buf.end());\n{indent}}}"

    def _gen_deserialization_logic(self, f: Field) -> str:
        t = f.type
        name = f.name
        code = []
        if t.is_list:
             code.append(f"        {{")
             code.append(f"            uint32_t byte_len_{name} = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;")
             code.append(f"            const uint8_t* end = data + byte_len_{name};")
             code.append(f"            while(data < end) {{")
             inner_type = Type(t.name, is_list=False)
             code.append(f"                {self._cpp_type(inner_type)} temp_{name};")
             code.append(self._deserialize_val_cpp(f"temp_{name}", inner_type, indent="                "))
             code.append(f"                obj.{name}.push_back(temp_{name});")
             code.append(f"            }}")
             code.append(f"        }}")
        else:
             code.append(self._deserialize_val_cpp(f"obj.{name}", t, indent="        "))
        return "\n".join(code)

    def _deserialize_val_cpp(self, expr_target: str, t: Type, indent: str) -> str:
        target_name = expr_target.replace('obj.','')
        if t.name == 'int':
             return f"{indent}{{ int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4; {expr_target} = val; }}"
        elif t.name == 'float':
             return f"{indent}{{ uint32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4; {expr_target} = *reinterpret_cast<float*>(&val); }}"
        elif t.name == 'bool':
             return f"{indent}{expr_target} = (data[0] != 0); data+=1; len-=1;"
        elif t.name == 'str':
             return f"{indent}{{\n{indent}    uint32_t slen = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;\n{indent}    {expr_target}.assign(reinterpret_cast<const char*>(data), slen); data+=slen; len-=slen;\n{indent}}}"
        else: # Struct
             return f"{indent}{expr_target} = {t.name}::deserialize(data, len);"

    def _cpp_type(self, t: Type) -> str:
        if t.is_list:
            return f"std::vector<{self._cpp_type(Type(t.name))}>"
            
        mapping = { 'int': 'int32_t', 'float': 'float', 'str': 'std::string', 'bool': 'bool', 'None': 'void' }
        if t.name in mapping: return mapping[t.name]
        return t.name
