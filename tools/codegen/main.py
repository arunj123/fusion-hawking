import sys
import os
import argparse
from .parser import PythonASTParser
from .generators.rust import RustGenerator
from .generators.python import PythonGenerator
from .generators.cpp import CppGenerator

def main():
    parser = argparse.ArgumentParser(description="Modular Code Generator")
    parser.add_argument("files", nargs="+", help="Path to IDL file(s) (Python)")
    args = parser.parse_args()
    
    all_structs = []
    all_services = []
    ast_parser = PythonASTParser()

    for idl_file in args.files:
        # 1. Parse
        print(f"Parsing {idl_file}...")
        structs, services = ast_parser.parse(idl_file)
        print(f"Found {len(structs)} structs and {len(services)} services.")
        all_structs.extend(structs)
        all_services.extend(services)
    
    structs, services = all_structs, all_services
    
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
    for filename, content in output_files.items():
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        print(f"Writing {filename}...")
        with open(filename, "w") as f:
            f.write(content)
            
    print("Code generation complete.")

if __name__ == "__main__":
    main()
