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

        lines.append("} // namespace generated")
        return {"src/generated/bindings.h": "\n".join(lines)}

    def _generate_struct(self, s: Struct) -> str:
        lines = []
        lines.append(f"struct {s.name} {{")
        for f in s.fields:
            lines.append(f"    {self._cpp_type(f.type)} {f.name};")
        lines.append("};")
        return "\n".join(lines)

    def _cpp_type(self, t: Type) -> str:
        if t.is_list:
            return f"std::vector<{self._cpp_type(Type(t.name))}>"
            
        mapping = { 'int': 'int32_t', 'float': 'float', 'str': 'std::string', 'bool': 'bool', 'None': 'void' }
        if t.name in mapping: return mapping[t.name]
        return t.name
