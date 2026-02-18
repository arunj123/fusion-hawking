"""
Fusion Hawking Code Generator

Generates language-specific bindings from Python IDL definitions.
Uses introspection-based scanning to discover services and types.

Usage:
    # Per-project generation (new, recommended):
    python -m tools.codegen.main --project integrated_apps \\
        --lang rust cpp ts \\
        --module examples.integrated_apps.idl

    # Legacy mode (backward compatible):
    python -m tools.codegen.main examples/integrated_apps/interface.py

    # Single language:
    python -m tools.codegen.main --project automotive_pubsub \\
        --lang rust \\
        --module examples.automotive_pubsub.idl
"""

import sys
import os
import argparse


def main():
    parser = argparse.ArgumentParser(description="Fusion Hawking Code Generator")

    # New per-project mode
    parser.add_argument("--project", help="Project name for isolated output (e.g. integrated_apps)")
    parser.add_argument("--module", help="Python module path to scan (e.g. examples.integrated_apps.idl)")
    parser.add_argument("--lang", nargs="+", default=["rust", "cpp", "ts"],
                        choices=["rust", "cpp", "ts", "python"],
                        help="Languages to generate (default: rust cpp ts)")
    parser.add_argument("--output-dir", default="build/generated",
                        help="Base output directory (default: build/generated)")

    # Legacy mode: positional IDL files
    parser.add_argument("files", nargs="*", help="Legacy: path to IDL file(s)")

    args = parser.parse_args()

    project_root = os.getcwd()

    if args.module:
        # === New introspection-based mode ===
        from .scanner import scan
        print(f"[codegen] Scanning module: {args.module}")
        structs, services = scan(args.module, project_root=project_root)
        print(f"[codegen] Found {len(structs)} types and {len(services)} services")

        # Determine output directory
        if args.project:
            output_dir = os.path.join(args.output_dir, args.project)
        else:
            output_dir = args.output_dir

    elif args.files:
        # === Legacy AST mode (backward compat) ===
        from .parser import PythonASTParser
        ast_parser = PythonASTParser()
        all_structs, all_services = [], []

        for idl_file in args.files:
            print(f"[codegen] Parsing {idl_file}...")
            structs, services = ast_parser.parse(idl_file)
            print(f"[codegen] Found {len(structs)} structs and {len(services)} services.")
            all_structs.extend(structs)
            all_services.extend(services)

        structs, services = all_structs, all_services
        output_dir = args.output_dir

        # Infer project name from file path for per-project output
        if args.project:
            output_dir = os.path.join(args.output_dir, args.project)

    else:
        parser.error("Either --module or positional IDL files are required.")
        return

    # ID validation (optional)
    try:
        from tools.id_manager.manager import IDManager
        print("[codegen] Validating Service IDs...")
        id_mgr = IDManager(project_root)
        id_mgr.scan_ids()
    except ImportError:
        pass
    except Exception as e:
        print(f"[codegen] Warning: ID validation failed: {e}")

    # Generate bindings
    generators = _get_generators(args.lang)
    output_files = {}
    for gen in generators:
        output_files.update(gen.generate(structs, services, output_dir=output_dir))

    # Write files
    for filename, content in output_files.items():
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        print(f"[codegen] Writing {filename}")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

    print(f"[codegen] Complete. Generated {len(output_files)} files in {output_dir}/")


def _get_generators(languages):
    """Create generator instances for each requested language."""
    generators = []
    for lang in languages:
        if lang == "rust":
            from .generators.rust import RustGenerator
            generators.append(RustGenerator())
        elif lang == "cpp":
            from .generators.cpp import CppGenerator
            generators.append(CppGenerator())
        elif lang == "ts":
            from .generators.ts import TsGenerator
            generators.append(TsGenerator())
        elif lang == "python":
            from .generators.python import PythonGenerator
            generators.append(PythonGenerator())
    return generators


if __name__ == "__main__":
    main()
