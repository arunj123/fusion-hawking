import ast
import sys
import os

def parse_type(annotation):
    if isinstance(annotation, ast.Name):
        return annotation.id
    elif isinstance(annotation, ast.Subscript): # For List[int]
        if isinstance(annotation.value, ast.Name) and annotation.value.id == 'List':
            inner = parse_type(annotation.slice)
            return f"Vec<{inner}>"
    return "Unknown"

def rust_type(py_type):
    mapping = {
        'int': 'i32',
        'float': 'f32', 
        'str': 'String',
        'bool': 'bool'
    }
    if py_type in mapping:
        return mapping[py_type]
    if py_type.startswith("Vec<"):
        inner = py_type[4:-1]
        return f"Vec<{rust_type(inner)}>"
    return py_type

def generate_rust(classes):
    lines = ["use crate::codec::{SomeIpSerialize, SomeIpDeserialize};", "use std::io::{Result, Write, Read};", ""]
    for cls_name, fields in classes.items():
        lines.append(f"#[derive(Debug, Clone, PartialEq)]")
        lines.append(f"pub struct {cls_name} {{")
        for fname, ftype in fields:
            lines.append(f"    pub {fname}: {rust_type(ftype)},")
        lines.append("}")
        lines.append("")
        
        # Serialize impl
        lines.append(f"impl SomeIpSerialize for {cls_name} {{")
        lines.append(f"    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {{")
        for fname, _ in fields:
            lines.append(f"        self.{fname}.serialize(writer)?;")
        lines.append("        Ok(())")
        lines.append("    }")
        lines.append("}")
        lines.append("")
        
        # Deserialize impl
        lines.append(f"impl SomeIpDeserialize for {cls_name} {{")
        lines.append(f"    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {{")
        lines.append(f"        Ok({cls_name} {{")
        for fname, ftype in fields:
             lines.append(f"            {fname}: <{rust_type(ftype)}>::deserialize(reader)?,")
        lines.append("        })")
        lines.append("    }")
        lines.append("}")
        lines.append("")
        
    return "\n".join(lines)

def generate_python(classes):
    lines = ["import struct", "from typing import List", "", "class SomeIpMessage:", "    pass", ""]
    
    # Primitive packing helpers
    lines.append("def pack_u32(val): return struct.pack('>I', val)")
    lines.append("def unpack_u32(data, off): return struct.unpack_from('>I', data, off)[0], off+4")
    lines.append("")

    for cls_name, fields in classes.items():
        lines.append(f"class {cls_name}:")
        # __init__ with valid hints
        args = []
        for fname, ftype in fields:
            hint = ftype
            if ftype.startswith("Vec<"):
                hint = f"List[{ftype[4:-1]}]" # Simple fix for Vec<int> -> List[int]
            args.append(f"{fname}: {hint}")
            
        lines.append(f"    def __init__(self, {', '.join(args)}):")
        for fname, _ in fields:
            lines.append(f"        self.{fname} = {fname}")
        lines.append("")
        
        # Serialize
        lines.append("    def serialize(self) -> bytes:")
        lines.append("        buffer = bytearray()")
        for fname, ftype in fields:
            if ftype.startswith("Vec<"):
                # Length prefixed list (u32)
                lines.append(f"        # {fname} list serialization")
                lines.append(f"        temp_buf = bytearray()")
                lines.append(f"        for item in self.{fname}:")
                inner = ftype[4:-1]
                if inner == 'int':
                     lines.append(f"            temp_buf.extend(struct.pack('>i', item))")
                elif inner == 'float':
                     lines.append(f"            temp_buf.extend(struct.pack('>f', item))")
                elif inner in ['i32', 'u32', 'f32']: # If we had strict types
                     fmt = { 'i32':'i', 'u32':'I', 'f32':'f' }[inner]
                     lines.append(f"            temp_buf.extend(struct.pack('>{fmt}', item))")
                elif inner == 'str' or inner == 'String':
                     lines.append(f"            b = item.encode('utf-8')")
                     lines.append(f"            temp_buf.extend(struct.pack('>I', len(b)))")
                     lines.append(f"            temp_buf.extend(b)")
                else:
                     lines.append(f"            temp_buf.extend(item.serialize())")
                
                lines.append(f"        buffer.extend(struct.pack('>I', len(temp_buf)))")
                lines.append(f"        buffer.extend(temp_buf)")
            
            elif ftype == 'int':
                 lines.append(f"        buffer.extend(struct.pack('>i', self.{fname}))")
            elif ftype == 'float':
                 lines.append(f"        buffer.extend(struct.pack('>f', self.{fname}))")
            elif ftype in ['i32', 'u32', 'f32']:
                 fmt = { 'i32':'i', 'u32':'I', 'f32':'f' }[ftype]
                 lines.append(f"        buffer.extend(struct.pack('>{fmt}', self.{fname}))")
            elif ftype == 'str' or ftype == 'String':
                lines.append(f"        b = self.{fname}.encode('utf-8')")
                lines.append(f"        buffer.extend(struct.pack('>I', len(b)))")
                lines.append(f"        buffer.extend(b)")
            else:
                 # Nested struct
                 lines.append(f"        buffer.extend(self.{fname}.serialize())")
        lines.append("        return bytes(buffer)")
        lines.append("")
    
    return "\n".join(lines)

def generate_cpp(classes):
    lines = ["#pragma once", "#include <vector>", "#include <string>", "#include <cstdint>", "#include <vector>", "#include <cstring>", "#include <algorithm>", ""]
    
    lines.append("""
    inline void write_u32_be(std::vector<uint8_t>& buf, uint32_t val) {
        buf.push_back((val >> 24) & 0xFF);
        buf.push_back((val >> 16) & 0xFF);
        buf.push_back((val >> 8) & 0xFF);
        buf.push_back(val & 0xFF);
    }
    """)

    for cls_name, fields in classes.items():
        lines.append(f"struct {cls_name} {{")
        for fname, ftype in fields:
            cpp_type = ftype
            if ftype == 'int': cpp_type = 'int32_t'
            elif ftype == 'float': cpp_type = 'float'
            elif ftype == 'bool': cpp_type = 'bool'
            elif ftype == 'str': cpp_type = 'std::string'
            elif ftype == 'i32': cpp_type = 'int32_t'
            elif ftype == 'u32': cpp_type = 'uint32_t'
            elif ftype == 'f32': cpp_type = 'float'
            elif ftype == 'String': cpp_type = 'std::string'
            elif ftype.startswith('Vec<'): 
                inner = ftype[4:-1]
                if inner == 'int': inner = 'int32_t'
                elif inner == 'str': inner = 'std::string'
                elif inner == 'i32': inner = 'int32_t'
                cpp_type = f"std::vector<{inner}>"
            
            lines.append(f"    {cpp_type} {fname};")
        lines.append("    ")
        
        lines.append("    std::vector<uint8_t> serialize() const {")
        lines.append("        std::vector<uint8_t> buffer;")
        lines.append("        // Serialization logic (Placeholder for MVP)")
        lines.append("        return buffer;")
        lines.append("    }")
        lines.append("};")
        lines.append("")
        
    return "\n".join(lines)

def main(filepath):
    with open(filepath, "r") as f:
        tree = ast.parse(f.read())
        
    classes = {}
    
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # Check for @dataclass decorator
            is_dataclass = any(isinstance(d, ast.Name) and d.id == 'dataclass' for d in node.decorator_list)
            if is_dataclass:
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign):
                        name = item.target.id
                        type_str = parse_type(item.annotation)
                        fields.append((name, type_str))
                classes[node.name] = fields

    rust_code = generate_rust(classes)
    py_code = generate_python(classes)
    cpp_code = generate_cpp(classes)
    
    os.makedirs("src/generated", exist_ok=True)
    with open("src/generated/mod.rs", "w") as f:
        f.write(rust_code)
    
    with open("src/generated/bindings.py", "w") as f:
        f.write(py_code)
        
    with open("src/generated/bindings.hpp", "w") as f:
        f.write(cpp_code)
        
    print("Generated src/generated/mod.rs, bindings.py, bindings.hpp")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python codegenerator.py <file.py>")
        sys.exit(1)
    main(sys.argv[1])
