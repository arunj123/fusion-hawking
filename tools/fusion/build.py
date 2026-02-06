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
        # Generate bindings for integrated apps
        cmd1 = [sys.executable, "-m", "tools.codegen.main", "examples/integrated_apps/interface.py"]
        res1 = self.run_command(cmd1, "codegen_bindings")
        
        # Generate bindings for automotive pubsub
        cmd2 = [sys.executable, "-m", "tools.codegen.main", "examples/automotive_pubsub/interface.py"]
        res2 = self.run_command(cmd2, "codegen_pubsub")
        
        return res1 and res2

    def build_rust(self):
        cmd = ["cargo", "build", "--examples", "--bins"]
        return self.run_command(cmd, "build_rust")

    def build_cpp(self):
        build_dir = "build"
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)
            
        cmake_config = ["cmake", ".."]
        if not self.run_command(cmake_config, "build_cpp_config", cwd=build_dir):
            return False
            
        cmake_build = ["cmake", "--build", ".", "--config", "Release"]
        return self.run_command(cmake_build, "build_cpp_compile", cwd=build_dir)
