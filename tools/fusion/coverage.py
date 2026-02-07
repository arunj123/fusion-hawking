import subprocess
import os
import shutil

class CoverageManager:
    def __init__(self, reporter, toolchains):
        self.reporter = reporter
        self.toolchains = toolchains

    def run_coverage(self, target="all"):
        print("\n--- Running Coverage ---")
        results = {}
        
        if target in ["all", "rust"]:
            results['coverage_rust'] = self._run_rust_coverage()
            
        if target in ["all", "python"]:
            results['coverage_python'] = self._run_python_coverage()
            
        if target in ["all", "cpp"]:
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
        env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
        
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
        else:
            # If it failed, dump the log to stdout for CI visibility
            log_path = self.reporter.get_log_path("python_integration")
            if os.path.exists(log_path):
                print(f"\n--- FAILURE LOG: python_integration ---")
                with open(log_path, "r") as f:
                    print(f.read())
                print(f"--- END LOG ---")
            return "FAIL"

    def _run_cpp_coverage(self):
        if os.name == 'nt':
            return self._run_cpp_coverage_windows()
        else:
            return self._run_cpp_coverage_linux()

    def _run_cpp_coverage_windows(self):
        if not self.toolchains.status.get("opencppcoverage"):
            print("Skipping C++ Coverage (OpenCppCoverage not found).")
            return "SKIPPED"

        print("Generating C++ Coverage (Windows)...")
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
            # Cleanup OpenCppCoverage log
            if os.path.exists("LastCoverageResults.log"):
                try:
                    shutil.move("LastCoverageResults.log", os.path.join(self.reporter.raw_logs_dir, "LastCoverageResults.log"))
                except:
                    pass
            return "PASS"
        return "FAIL"

    def _run_cpp_coverage_linux(self):
        if not shutil.which("lcov"):
             print("Skipping C++ Coverage (lcov not found).")
             return "SKIPPED"

        print("Generating C++ Coverage (Linux)...")
        
        # Diagnostics: List build directory
        print("Checking build directory content...")
        build_dir = "build"
        if os.path.exists(build_dir):
            files = []
            for root, _, filenames in os.walk(build_dir):
                for f in filenames:
                    files.append(os.path.relpath(os.path.join(root, f), build_dir))
            print(f"  [DEBUG] Found {len(files)} files in build/")
            # Look for the test binary
            potential_bins = [f for f in files if "cpp_test" in f]
            print(f"  [DEBUG] Potential test binaries: {potential_bins}")
        else:
            print("  [ERROR] build directory not found!")
            return "FAIL"

        cpp_test_exe = "build/cpp_test"
        if not os.path.exists(cpp_test_exe):
            # Try to find it if it moved
            found = False
            for root, _, filenames in os.walk(build_dir):
                if "cpp_test" in filenames:
                    cpp_test_exe = os.path.join(root, "cpp_test")
                    print(f"  [INFO] Found cpp_test at alternative path: {cpp_test_exe}")
                    found = True
                    break
            if not found:
                print("Skipping C++ Coverage (Executable not found).")
                return "SKIPPED"

        out_dir = os.path.join(self.reporter.coverage_dir, "cpp")
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        # 1. Reset counters
        subprocess.run(["lcov", "--directory", build_dir, "--zerocounters"], check=False)
        
        # 2. Run Test
        header = f"=== FUSION C++ COVERAGE TEST RUN ===\n"
        print(f"  Running test binary: {cpp_test_exe}")
        if not self._run([f"./{cpp_test_exe}"], "cpp_integration_run", header=header):
            print("Warning: C++ test returned non-zero during coverage run")
            self._dump_log("cpp_integration_run")

        # Diagnostics: Check for .gcda files
        gcda_files = []
        for root, _, filenames in os.walk(build_dir):
            for f in filenames:
                if f.endswith(".gcda"):
                    gcda_files.append(os.path.join(root, f))
        print(f"  [DEBUG] Found {len(gcda_files)} .gcda files after test run.")
        if len(gcda_files) == 0:
            print("  [ERROR] No .gcda files generated. Check if binary was built with --coverage and ran successfully.")
            # Dump test output regardless of return code to see if it actually ran
            self._dump_log("cpp_integration_run")

        # 3. Capture coverage
        info_file = os.path.join(self.reporter.coverage_dir, "cpp", "coverage.info")
        capture_cmd = ["lcov", "--directory", build_dir, "--capture", "--output-file", info_file]
        # Base directory might help LCOV 2.0
        capture_cmd.extend(["--base-directory", os.getcwd()])
        
        if not self._run(capture_cmd, "cpp_coverage_capture"):
            self._dump_log("cpp_coverage_capture")
            return "FAIL"

        # 4. Filter (exclude tests, examples, tools)
        filter_cmd = ["lcov", "--remove", info_file, "/usr/*", "*/tests/*", "*/examples/*", "*/build/*", "--output-file", info_file]
        self._run(filter_cmd, "cpp_coverage_filter")

        # 5. Generate HTML
        gen_cmd = ["genhtml", info_file, "--output-directory", out_dir]
        if self._run(gen_cmd, "cpp_coverage_html"):
            return "PASS"
        else:
            self._dump_log("cpp_coverage_html")
            return "FAIL"

    def _dump_log(self, log_name):
        log_path = self.reporter.get_log_path(log_name)
        if os.path.exists(log_path):
            print(f"\n--- FAILURE LOG: {log_name} ---")
            with open(log_path, "r") as f:
                print(f.read())
            print(f"--- END LOG ---")

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
