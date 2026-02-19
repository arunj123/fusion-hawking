import subprocess
import os
import shutil
import sys

class CoverageManager:
    def __init__(self, reporter, toolchains, env_caps=None):
        self.reporter = reporter
        self.toolchains = toolchains
        self.env_caps = env_caps or {}

    def _build_pytest_marker_expr(self):
        """Build a pytest -m expression to deselect tests based on capabilities."""
        caps = self.env_caps
        excluded = []
        if not caps.get('has_netns'):
            excluded.append('needs_netns')
        if not caps.get('has_multicast'):
            excluded.append('needs_multicast')
        if not caps.get('has_ipv6'):
            excluded.append('needs_ipv6')
        if not caps.get('has_veth'):
            excluded.append('needs_veth')
        if excluded:
            expr = ' and '.join(f'not {m}' for m in excluded)
            return expr
        return None

    def run_coverage(self, target="all"):
        print("\n--- Running Coverage ---")
        if self.env_caps:
             print("  [cov] Environment capabilities:")
             for key, val in self.env_caps.items():
                 if key != 'interfaces':
                     icon = '[v]' if val else '[x]' if isinstance(val, bool) else '   '
                     print(f"    {icon} {key}: {val}")
        
        results = {}
        
        if target in ["all", "rust"]:
            results['coverage_rust'] = self._run_rust_coverage()
            
        if target in ["all", "python"]:
            results['coverage_python'] = self._run_python_coverage()
            
        if target in ["all", "cpp"]:
            results['coverage_cpp'] = self._run_cpp_coverage()
            
        if target in ["all", "js"]:
            results['coverage_js'] = self._run_js_coverage()
            
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
        env["PYTHONPATH"] = os.pathsep.join([
            os.getcwd(), "src/python", "build",
            "build/generated/integrated_apps/python",
            "build/generated/automotive_pubsub/python",
        ])
        env["FUSION_LOG_DIR"] = str(self.reporter.raw_logs_dir)
        
        # Use a distinct log name for the runner, preserving 'python_integration.log' for the app under test
        runner_log_name = "coverage_python_pytest"
        
        cmd = ["pytest", "--cov=src/python", 
               f"--cov-report=html:{os.path.join(self.reporter.coverage_dir, 'python')}",
               "tests/"]
        
        # Apply marker filters
        marker_expr = self._build_pytest_marker_expr()
        if marker_expr:
            cmd.extend(["-m", marker_expr])
        
        header = f"=== FUSION COVERAGE RUNNER ===\nCommand: {' '.join(cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\nMarker Filter: {marker_expr}\n==============================\n\n"
        
        if self._run(cmd, runner_log_name, env=env, header=header):
            return "PASS"
        else:
            # If it failed, dump the runner log
            self._dump_log(runner_log_name)
            
            # Also dump component logs which might contain the actual failure details
            print("\n  [INFO] Dumping component logs due to coverage failure:")
            for app_log in ["python_integration.log", "cpp_integration.log", "rust_integration.log"]:
                 log_path = os.path.join(self.reporter.raw_logs_dir, app_log)
                 if os.path.exists(log_path):
                     print(f"\n--- COMPONENT LOG: {app_log} ---")
                     try:
                         with open(log_path, "r", encoding='utf-8', errors='ignore') as f:
                             print(f.read())
                     except Exception as e:
                         print(f"Error reading {app_log}: {e}")
                     print(f"--- END COMPONENT LOG ---")
            
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
        # Use a distinct log name
        runner_log_name = "coverage_cpp_test"
        
        cmd = ["OpenCppCoverage", "--sources", "src\\cpp", 
               f"--export_type", f"html:{out_dir}", 
               "--", cpp_test_exe]
        
        header = f"=== FUSION COVERAGE RUNNER ===\nCommand: {' '.join(cmd)}\nPWD: {os.getcwd()}\n==============================\n\n"

        if self._run(cmd, runner_log_name, header=header):
            # Cleanup OpenCppCoverage log
            if os.path.exists("LastCoverageResults.log"):
                try:
                    shutil.move("LastCoverageResults.log", os.path.join(self.reporter.raw_logs_dir, "LastCoverageResults.log"))
                except:
                    pass
            return "PASS"
        else:
             self._dump_log(runner_log_name)
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
        # Use distinct log name
        runner_log_name = "coverage_cpp_run"
        
        if not self._run([f"./{cpp_test_exe}"], runner_log_name, header=header):
            print("Warning: C++ test returned non-zero during coverage run")
            self._dump_log(runner_log_name)

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
            self._dump_log(runner_log_name)

        # 3. Capture coverage
        info_file = os.path.join(self.reporter.coverage_dir, "cpp", "coverage.info")
        capture_cmd = ["lcov", "--directory", build_dir, "--capture", "--output-file", info_file]
        # Base directory might help LCOV 2.0
        capture_cmd.extend(["--base-directory", os.getcwd()])
        
        if not self._run(capture_cmd, "coverage_cpp_capture"):
            self._dump_log("coverage_cpp_capture")
            return "FAIL"

        # 4. Filter (exclude tests, examples, tools)
        filter_cmd = ["lcov", "--remove", info_file, "/usr/*", "*/tests/*", "*/examples/*", "*/build/*", "--output-file", info_file]
        self._run(filter_cmd, "coverage_cpp_filter")

        # 5. Generate HTML
        gen_cmd = ["genhtml", info_file, "--output-directory", out_dir]
        if self._run(gen_cmd, "coverage_cpp_html"):
            return "PASS"
        else:
            self._dump_log("coverage_cpp_html")
            return "FAIL"

    def _run_js_coverage(self):
        print("Generating JS Coverage (c8)...")
        js_dir = "src/js"
        if not os.path.exists(js_dir):
            return "SKIPPED (src/js not found)"

        npm_bin = "npm.cmd" if os.name == "nt" else "npm"
        # We use --prefix to avoid needing cwd in _run
        cmd = [npm_bin, "--prefix", js_dir, "run", "test:coverage"]
        
        header = f"=== FUSION JS COVERAGE RUNNER ===\nCommand: {' '.join(cmd)}\n==============================\n\n"
        
        if self._run(cmd, "coverage_js", header=header):
            return "PASS"
        else:
            self._dump_log("coverage_js")
            return "FAIL"

    def _dump_log(self, log_name):
        log_path = self.reporter.get_log_path(log_name)
        if os.path.exists(log_path):
            print(f"\n--- FAILURE LOG: {log_name} ---")
            with open(log_path, "r", errors='ignore') as f:
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
