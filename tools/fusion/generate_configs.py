"""
Configuration Generator

Scans example projects and generates per-project config.json files
in build/generated/{project}/config.json.

Usage:
    python -m tools.fusion.generate_configs
    python -m tools.fusion.generate_configs --project integrated_apps
"""
import os
import sys
import json
import shutil
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def find_config(project_dir: str) -> str | None:
    """Find config.json in a project directory."""
    candidates = [
        os.path.join(project_dir, "config.json"),
        os.path.join(project_dir, "config", "config.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def generate_config(project_name: str, project_dir: str, output_base: str = "build/generated") -> str | None:
    """Generate/copy config.json for a project into its generated output dir."""
    src = find_config(project_dir)
    if not src:
        print(f"[generate_configs] No config.json found in {project_dir}, skipping.")
        return None

    dest_dir = os.path.join(output_base, project_name)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "config.json")

    # Copy and validate
    shutil.copy2(src, dest)
    print(f"[generate_configs] {src} -> {dest}")

    # Also copy to logs
    log_dir = os.path.join("logs", project_name)
    os.makedirs(log_dir, exist_ok=True)
    log_dest = os.path.join(log_dir, "config.json")
    shutil.copy2(src, log_dest)
    print(f"[generate_configs] {src} -> {log_dest}")

    return dest


def generate_all(output_base: str = "build/generated"):
    """Scan examples/ for projects with config.json and generate configs."""
    examples_dir = os.path.join(ROOT, "examples")
    generated = []

    for entry in os.listdir(examples_dir):
        project_dir = os.path.join(examples_dir, entry)
        if os.path.isdir(project_dir):
            result = generate_config(entry, project_dir, output_base)
            if result:
                generated.append(result)

    # Also generate a root config.json in build/generated/ for backward compat
    root_config = os.path.join(ROOT, "examples", "config.json")
    if os.path.exists(root_config):
        dest = os.path.join(output_base, "config.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(root_config, dest)
        print(f"[generate_configs] {root_config} -> {dest} (root compat)")
        generated.append(dest)

    print(f"[generate_configs] Generated {len(generated)} config files.")
    return generated


def main():
    parser = argparse.ArgumentParser(description="Generate per-project config.json files")
    parser.add_argument("--project", help="Generate config for a specific project only")
    parser.add_argument("--output-dir", default="build/generated", help="Base output directory")
    args = parser.parse_args()

    os.chdir(ROOT)

    if args.project:
        project_dir = os.path.join(ROOT, "examples", args.project)
        if not os.path.isdir(project_dir):
            print(f"Error: Project directory not found: {project_dir}")
            sys.exit(1)
        generate_config(args.project, project_dir, args.output_dir)
    else:
        generate_all(args.output_dir)


if __name__ == "__main__":
    main()
