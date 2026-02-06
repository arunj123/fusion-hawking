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

    def generate_bindings(self):
        import sys
        # Generate all bindings in one call to avoid overwriting files
        cmd = [
            sys.executable, "-m", "tools.codegen.main", 
            "examples/integrated_apps/interface.py",
            "examples/automotive_pubsub/interface.py"
        ]
        return self.run_command(cmd, "codegen_all")

    def build_rust(self):
        # Core + simple bins
        cmd = ["cargo", "build", "--examples", "--bins"]
        if not self.run_command(cmd, "build_rust_core"):
            return False
        
        # Standalone Demo
        cmd_demo = ["cargo", "build"]
        return self.run_command(cmd_demo, "build_rust_demo", cwd="examples/integrated_apps/rust_app")

    def build_cpp(self):
        # Core Library + Simple Bins + Tests (Root CMake)
        build_dir = "build"
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)
            
        cmake_config = ["cmake", ".."]
        if not self.run_command(cmake_config, "build_cpp_config", cwd=build_dir):
            return False
            
        cmake_build = ["cmake", "--build", ".", "--config", "Release"]
        if not self.run_command(cmake_build, "build_cpp_compile", cwd=build_dir):
            return False

        # Standalone Demo (Sub CMake)
        demo_dir = "examples/integrated_apps/cpp_app"
        demo_build_dir = os.path.join(demo_dir, "build")
        if not os.path.exists(demo_build_dir):
            os.makedirs(demo_build_dir)

        if not self.run_command(["cmake", ".."], "build_cpp_demo_config", cwd=demo_build_dir):
            return False
        
        return self.run_command(["cmake", "--build", ".", "--config", "Release"], "build_cpp_demo_compile", cwd=demo_build_dir)
