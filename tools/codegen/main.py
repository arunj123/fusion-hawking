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
    parser.add_argument("--output-dir", default="build/generated", help="Base output directory for generated code")
    args = parser.parse_args()
    
    # 0. Validate IDs (if running from project root context)
    try:
        from tools.id_manager.manager import IDManager
        print("Validating Service IDs...")
        id_mgr = IDManager(os.getcwd())
        # id_mgr.validate() returns True currently, but logs warnings. 
        # Future strict mode could raise exception.
        id_mgr.scan_ids() 
    except ImportError:
        print("Warning: tools.id_manager not found. Skipping ID validation.")

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
        output_files.update(gen.generate(structs, services, output_dir=args.output_dir))
        
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
