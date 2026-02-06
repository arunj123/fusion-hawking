import subprocess
import os
import shutil

class CoverageManager:
    def __init__(self, reporter, toolchains):
        self.reporter = reporter
        self.toolchains = toolchains

    def run_coverage(self):
        print("\n--- Running Coverage ---")
        results = {}
        results['coverage_rust'] = self._run_rust_coverage()
        results['coverage_python'] = self._run_python_coverage()
        results['coverage_cpp'] = self._run_cpp_coverage()
        return results
        
    def _run_rust_coverage(self):
        if not shutil.which("cargo-llvm-cov"):
            self.toolchains.status['rust_cov'] = False
            return "SKIPPED (Missing cargo-llvm-cov)"

        print("Generating Rust Coverage...")
        cmd = ["cargo", "llvm-cov", "--html", "--output-dir", 
               os.path.join(self.reporter.coverage_dir, "rust"),
               "--ignore-filename-regex", "tests|examples|tools"]
        
        if self._run(cmd, "coverage_rust"):
            return "PASS"
        return "FAIL"

    def _run_python_coverage(self):
        print("Generating Python Coverage...")
        env = os.environ.copy()
        env["PYTHONPATH"] = "src/python;build;build/generated/python"
        
        cmd = ["pytest", "--cov=src/python", 
               f"--cov-report=html:{os.path.join(self.reporter.coverage_dir, 'python')}",
               "tests/"]
        
        # Log injection happens in _run, but we need to control the header
        # _run doesn't support custom headers easily without modification.
        # So we'll overload _run or prep the file first.
        # Actually _run opens the file in "w" mode, so it overwrites.
        # Let's modify _run to accept a header_info dict.
        # Or just write it here manually and use append mode in _run? No, _run logic...
        # Simplest: manually write header, then call _run with append mode? _run hardcodes "w".
        
        # Let's modify _run to accept 'header' argument.
        header = f"=== FUSION COVERAGE RUNNER ===\nCommand: {' '.join(cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n==============================\n\n"
        
        if self._run(cmd, "python_integration", env=env, header=header):
            return "PASS"
        return "FAIL"

    def _run_cpp_coverage(self):
        if not self.toolchains.status.get("opencppcoverage"):
            print("Skipping C++ Coverage (OpenCppCoverage not found).")
            return "SKIPPED"

        print("Generating C++ Coverage...")
        cpp_test_exe = "build/Release/cpp_test.exe"
        if not os.path.exists(cpp_test_exe):
            print("Skipping C++ Coverage (Executable not found).")
            return "SKIPPED"
            
        out_dir = os.path.join(self.reporter.coverage_dir, "cpp")
        cmd = ["OpenCppCoverage", "--sources", "src\\cpp", 
               f"--export_type", f"html:{out_dir}", 
               "--", cpp_test_exe]
        
        header = f"=== FUSION COVERAGE RUNNER ===\nCommand: {' '.join(cmd)}\nPWD: {os.getcwd()}\n==============================\n\n"

        if self._run(cmd, "cpp_integration", header=header):
            return "PASS"
        return "FAIL"

    def _run(self, cmd, log_name, env=None, header=None):
        log_path = self.reporter.get_log_path(log_name)
        with open(log_path, "w") as f:
            if header:
                f.write(header)
                f.flush()
            try:
                ret = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, check=False)
                return ret.returncode == 0
            except Exception as e:
                f.write(f"\nExecution failed: {e}")
                return False
