import subprocess
import os

class Builder:
    def __init__(self, reporter):
        self.reporter = reporter

    def run_command(self, cmd, log_name, cwd=None):
        log_path = self.reporter.get_log_path(log_name)
        print(f"Running: {' '.join(cmd)} > {log_name}.log")
        
        with open(log_path, "w") as f:
            try:
                proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=cwd, check=True)
                return True
            except subprocess.CalledProcessError:
                f.flush()
                with open(log_path, "r") as log_file:
                    print(f"--- FAILURE LOG: {log_name} ---")
                    print(log_file.read())
                    print(f"--- END LOG ---")
                return False
            except FileNotFoundError as e:
                f.write(f"\n[ERROR] Command not found: {e}\n")
                print(f"[ERROR] Command not found: {e}")
                return False

    def generate_bindings(self):
        import sys

        # Per-project IDL modules (new introspection-based approach)
        projects = [
            ("integrated_apps",   "examples.integrated_apps.idl"),
            ("automotive_pubsub", "examples.automotive_pubsub.idl"),
        ]

        # IDL package directories for timestamp tracking
        idl_dirs = [
            "examples/integrated_apps/idl",
            "examples/automotive_pubsub/idl",
            "examples/versioning_demo/interface.py",
        ]

        output_dir = "build/generated"
        marker_file = os.path.join(output_dir, ".codegen_timestamp")

        # Check if we should regenerate
        regenerate = False
        if not os.path.exists(marker_file):
            print("[codegen] Marker file not found. Regenerating...")
            regenerate = True
        else:
            try:
                marker_mtime = os.path.getmtime(marker_file)
                for idl_path in idl_dirs:
                    abs_path = os.path.abspath(idl_path)
                    if os.path.isdir(abs_path):
                        for root, _, files in os.walk(abs_path):
                            for fname in files:
                                if fname.endswith(".py"):
                                    fpath = os.path.join(root, fname)
                                    if os.path.getmtime(fpath) > marker_mtime:
                                        print(f"[codegen] {fpath} changed. Regenerating...")
                                        regenerate = True
                                        break
                            if regenerate:
                                break
                    elif os.path.exists(abs_path):
                        if os.path.getmtime(abs_path) > marker_mtime:
                            print(f"[codegen] {idl_path} changed. Regenerating...")
                            regenerate = True
                    if regenerate:
                        break
            except Exception as e:
                print(f"[codegen] Error checking timestamps: {e}. Regenerating...")
                regenerate = True

        if not regenerate:
            print("[codegen] Bindings are up-to-date. Skipping generation.")
            return True

        # Generate per-project bindings (Rust + C++ + TS)
        success = True
        for project_name, module_path in projects:
            cmd = [
                sys.executable, "-m", "tools.codegen.main",
                "--project", project_name,
                "--lang", "rust", "cpp", "ts",
                "--module", module_path,
                "--output-dir", output_dir,
            ]
            if not self.run_command(cmd, f"codegen_{project_name}"):
                success = False
                break

        # Also generate Python stubs for backward compat (python_app still uses them)
        if success:
            for project_name, module_path in projects:
                cmd = [
                    sys.executable, "-m", "tools.codegen.main",
                    "--project", project_name,
                    "--lang", "python",
                    "--module", module_path,
                    "--output-dir", output_dir,
                ]
                # Non-fatal: Python apps will migrate to zero-codegen
                self.run_command(cmd, f"codegen_{project_name}_python")

        if success:
            try:
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
                with open(marker_file, "w") as f:
                    import datetime
                    f.write(str(datetime.datetime.now()))
            except Exception as e:
                print(f"[codegen] Warning: Could not update marker: {e}")

            # Generate per-project config.json files
            cmd_configs = [sys.executable, "-m", "tools.fusion.generate_configs"]
            self.run_command(cmd_configs, "codegen_configs")

        return success

    def build_rust(self, packet_dump=False):
        # Core + simple bins
        cmd = ["cargo", "build", "--examples", "--bins"]
        if packet_dump:
            cmd.extend(["--features", "packet-dump"])
            
        if not self.run_command(cmd, "build_rust_core"):
            return False
        
        # Standalone Demo
        cmd_demo = ["cargo", "build"]
        if packet_dump:
            cmd_demo.extend(["--features", "packet-dump"])
            
        if not self.run_command(cmd_demo, "build_rust_demo", cwd="examples/integrated_apps/rust_app"):
            return False

        # Automotive Pub-Sub Fusion Node
        return self.run_command(cmd_demo, "build_rust_fusion", cwd="examples/automotive_pubsub/rust_fusion")

    def build_cpp(self, with_coverage=False, packet_dump=False):
        # Core Library + Simple Bins + Tests (Root CMake)
        # Use separate build directory for non-Windows (or WSL) to avoid CMakeCache conflicts
        # when switching between environments on the same filesystem.
        build_dir = "build"
        if os.name != 'nt':
            build_dir = "build_linux"
            
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)
            
        cmake_config = ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"]
        if with_coverage:
            cmake_config.append("-DFUSION_ENABLE_COVERAGE=ON")
        if packet_dump:
            cmake_config.append("-DFUSION_PACKET_DUMP=ON")
            
        if not self.run_command(cmake_config, "build_cpp_config", cwd=build_dir):
            return False
            
        cmake_build = ["cmake", "--build", ".", "--config", "Release"]
        if not self.run_command(cmake_build, "build_cpp_compile", cwd=build_dir):
            return False
            
        return True

    def build_js(self):
        """Builds all JS/TS projects (core and examples)."""
        npm_bin = "npm.cmd" if os.name == "nt" else "npm"
        
        js_projects = [
            "src/js",
            "examples/integrated_apps/js_app",
            "examples/automotive_pubsub/js_adas",
            "examples/simple_no_sd/js",
            "examples/someipy_demo/js_client"
        ]
        
        for project_path in js_projects:
            full_path = os.path.join(os.getcwd(), project_path)
            if not os.path.exists(full_path):
                print(f"[WARN] JS Project path not found: {project_path}")
                continue
            
            # Skip if no package.json (e.g. simple vanilla JS files)
            pkg_json = os.path.join(full_path, "package.json")
            if not os.path.exists(pkg_json):
                print(f"Skipping JS build for {project_path} (no package.json)")
                continue
                
            log_suffix = project_path.replace("/", "_").replace("\\", "_")
            print(f"Building JS project: {project_path}")
            
            # Install
            if not self.run_command([npm_bin, "install"], f"build_js_install_{log_suffix}", cwd=project_path):
                return False
                
            # Build (only if package.json has a build script)
            # Most of our JS projects have a build script for tsc
            if not self.run_command([npm_bin, "run", "build"], f"build_js_compile_{log_suffix}", cwd=project_path):
                return False
                
        return True
