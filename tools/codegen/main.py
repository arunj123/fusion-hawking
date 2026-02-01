import sys
import os
import argparse
from .parser import PythonASTParser
from .generators.rust import RustGenerator
from .generators.python import PythonGenerator
from .generators.cpp import CppGenerator

def main():
    parser = argparse.ArgumentParser(description="Modular Code Generator")
    parser.add_argument("file", help="Path to IDL file (Python)")
    args = parser.parse_args()
    
    # 1. Parse
    print(f"Parsing {args.file}...")
    ast_parser = PythonASTParser()
    structs, services = ast_parser.parse(args.file)
    print(f"Found {len(structs)} structs and {len(services)} services.")
    
    # 2. Generate
    generators = [
        RustGenerator(),
        PythonGenerator(),
        CppGenerator()
    ]
    
    output_files = {}
    for gen in generators:
        output_files.update(gen.generate(structs, services))
        
    # 3. Write
    os.makedirs("src/generated", exist_ok=True)
    for filename, content in output_files.items():
        print(f"Writing {filename}...")
        with open(filename, "w") as f:
            f.write(content)
            
    print("Code generation complete.")

if __name__ == "__main__":
    main()
