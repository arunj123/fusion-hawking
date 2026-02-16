import subprocess
import os
import time
import threading
import json
import sys
import datetime
import shutil

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.getcwd())

from tools.fusion.utils import _get_env as get_environment
from tools.fusion.config_gen import SmartConfigFactory
from tools.fusion.report import Reporter as TestReporter
from tools.fusion.execution import AppRunner

class Tester:
    def __init__(self, reporter, builder, env_caps=None):
        self.reporter = reporter
        self.builder = builder
        self.env_caps = env_caps or {}
        self._cleanup_zombies()

    def _cleanup_zombies(self):
        """Clean up any lingering processes from previous runs to avoid port conflicts."""
        print("  [setup] Cleaning up lingering processes...")
        my_pid = os.getpid()
        
        # 1. Kill dedicated apps (always safe)
        apps = ["cpp_app.exe", "rust_app_demo.exe", "node.exe"] if os.name == 'nt' else ["cpp_app", "rust_app_demo", "node"]
        for proc in apps:
            try:
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/IM", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["pkill", "-9", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass

        # 2. Specifically target processes holding the SOME/IP SD ports (30890, 31890)
        ports = [30890, 31890]
        for port in ports:
            try:
                if os.name == 'nt':
                    output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode('utf-8', 'ignore')
                    for line in output.strip().split('\n'):
                        parts = line.split()
                        if len(parts) > 4:
                            pid = parts[-1]
                            if pid.isdigit() and int(pid) != my_pid:
                                subprocess.run(["taskkill", "/F", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["fuser", "-k", f"{port}/udp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run(["fuser", "-k", f"{port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass

    def _get_flattened_caps(self):
        """Flatten nested NetworkEnvironment capabilities into a simple dict."""
        caps = {}
        if not self.env_caps:
            return caps
            
        # OS and Basic info
        caps['os'] = self.env_caps.get('os')
        caps['is_wsl'] = self.env_caps.get('is_wsl', False)
        
        # Determine if we are using the nested structure (NetworkEnvironment.to_dict)
        # or the legacy flat structure (detect_environment)
        is_nested = 'capabilities' in self.env_caps
        
        if is_nested:
            # New format (NetworkEnvironment.to_dict)
            base_caps = self.env_caps.get('capabilities', {})
            caps['has_ipv4'] = base_caps.get('ipv4', False)
            caps['has_ipv6'] = base_caps.get('ipv6', False)
            caps['has_multicast'] = base_caps.get('multicast', False)
            
            vnet = self.env_caps.get('vnet', {})
            caps['has_netns'] = vnet.get('available', False)
            caps['has_veth'] = vnet.get('available', False)
        else:
            # Legacy flat format (detect_environment)
            caps['has_ipv4'] = self.env_caps.get('has_ipv4', False)
            caps['has_ipv6'] = self.env_caps.get('has_ipv6', False)
            caps['has_multicast'] = self.env_caps.get('has_multicast', False)
            caps['has_netns'] = self.env_caps.get('has_netns', False)
            caps['has_veth'] = self.env_caps.get('has_veth', False)
        
        return caps

    def _build_pytest_marker_expr(self):
        """Build a pytest -m expression to deselect tests whose required
        capabilities are not present in the current environment."""
        caps = self._get_flattened_caps()
        
        # Explicit check for mandatory capabilities used in markers
        # If they are missing from detect, they default to False
        has_netns = caps.get('has_netns', False)
        has_multicast = caps.get('has_multicast', False)
        has_ipv6 = caps.get('has_ipv6', False)
        has_veth = caps.get('has_veth', False)

        excluded = []
        if not has_netns:
            excluded.append('needs_netns')
        if not has_multicast:
            excluded.append('needs_multicast')
        if not has_ipv6:
            excluded.append('needs_ipv6')
        if not has_veth:
            excluded.append('needs_veth')
        
        # Always print caps for debugging
        print(f"  [caps] env_caps keys: {list(self.env_caps.keys())}")
        print(f"  [caps] Flattened Caps: {caps}")
        
        if excluded:
            expr = ' and '.join(f'not {m}' for m in excluded)
            print(f"  [caps] pytest deselection: -m \"{expr}\"")
            return expr
        else:
            print("  [caps] pytest: No tests excluded (full capability)")
        return None

    def _run_and_tee(self, cmd, log_path, env=None, cwd=None, header=None):
        """Run a command, streaming stdout to console AND capturing to log file (absolute path)."""
        
        # Prepare header
        with open(log_path, "w") as f:
            if header:
                f.write(header)
                f.write("\n")
                f.flush()
        
        # Open in append mode for teeing
        try:
            with open(log_path, "a") as f:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, # Merge stderr into stdout
                    env=env,
                    cwd=cwd,
                    text=True,
                    bufsize=1, # Line buffered
                    encoding='utf-8', 
                    errors='replace'
                )
                
                # Stream output
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        f.write(line)
                        f.flush()
                
                return_code = process.wait()
                if return_code != 0:
                    print(f"  [error] Command failed with exit code {return_code}")
                return return_code == 0
        except Exception as e:
            print(f"Error running {cmd}: {e}")
            return False

    def _get_cpp_binary_path(self, name):
        """Helper to find C++ binary path based on platform."""
        search_paths = []
        if os.name == 'nt':
            search_paths.append(os.path.join("examples", "integrated_apps", "cpp_app", "build", "Release", f"{name}.exe"))
            search_paths.append(os.path.join("examples", "integrated_apps", "cpp_app", "build", f"{name}.exe"))
            search_paths.append(os.path.join("build", "Release", f"{name}.exe"))
            search_paths.append(os.path.join("build", f"{name}.exe"))
        else:
            search_paths.append(os.path.join("examples", "integrated_apps", "cpp_app", "build", name))
            search_paths.append(os.path.join("build", name))
            search_paths.append(os.path.join("build_linux", name))
            search_paths.append(os.path.join("build", "examples", "integrated_apps", "cpp_app", name))
            
        for path in search_paths:
            if os.path.isfile(path): return path
            
        # Fallback: Recursive Search in build dir
        if os.path.exists("build"):
            for root, dirs, files in os.walk("build"):
                if name in files or f"{name}.exe" in files:
                    found_path = os.path.join(root, name if name in files else f"{name}.exe")
                    return found_path
        
        return None

    def run_unit_tests(self):
        print("\n--- Running Unit Tests ---")
        if self.env_caps:
            print("  [env] Environment capabilities:")
            for key, val in self.env_caps.items():
                if key == 'interfaces':
                    print(f"    interfaces: {', '.join(val) if val else '(none)'}")
                else:
                    icon = '[v]' if val else '[x]' if isinstance(val, bool) else '   '
                    print(f"    {icon} {key}: {val}")
        
        results = {"steps": []}
        
        # Rust (cargo test streams by default if run_command uses defaults)
        print("  Running Rust tests...")
        
        # Log directory for Rust tests
        log_dir = os.path.join(self.reporter.raw_logs_dir, "unit_tests", "rust")
        os.makedirs(log_dir, exist_ok=True)
        rust_log = os.path.join(log_dir, "test_rust.log")
        
        header = f"=== FUSION RUST TEST ===\nCommand: cargo test\nPWD: {os.getcwd()}\n========================\n\n"
        if self._run_and_tee(["cargo", "test"], rust_log, header=header):
            results["rust"] = "PASS"
        else:
            results["rust"] = "FAIL"
        
        results["steps"].append({
            "name": "Rust Unit Tests",
            "status": results["rust"],
            "log": "unit_tests/rust/test_rust.log",
            "details": "Ran 'cargo test' for core runtime"
        })

        # Python
        print("  Running Python tests...")
        py_results = self._run_python_tests()
        py_steps = py_results.pop("steps", [])
        results.update(py_results)
        results["steps"].extend(py_steps)

        # C++
        print("  Running C++ tests...")
        cpp_status = self._run_cpp_tests()
        results["cpp"] = cpp_status
        results["steps"].append({
            "name": "C++ Unit Tests",
            "status": cpp_status,
            "log": "unit_tests/cpp/test_cpp.log",
            "details": "Ran 'cpp_test' binary"
        })

        print(f"  Unit test results: {results}")
        
        # JS
        print("  Running JS tests...")
        if self._run_js_tests() == "PASS":
            results["js"] = "PASS"
        else:
            results["js"] = "FAIL"
            
        results["steps"].append({
            "name": "JS/TS Unit Tests",
            "status": results["js"],
            "log": "unit_tests/js/test_js.log",
            "details": "Ran 'npm test' in src/js"
        })

        return results

    def _run_python_tests(self):
        results = {"steps": []}
        # Python
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
        env["FUSION_LOG_DIR"] = str(self.reporter.raw_logs_dir)
        
        log_dir = os.path.join(self.reporter.raw_logs_dir, "unit_tests", "python")
        os.makedirs(log_dir, exist_ok=True)

        # 1. Unittest
        py_cmd = [sys.executable, "-m", "unittest", "discover", "tests", "-v"]
        header = f"=== FUSION UNIT TEST ===\nCommand: {' '.join(py_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n========================\n\n"
        
        unittest_log = os.path.join(log_dir, "test_python_unittest.log")
        status = "PASS" if self._run_and_tee(py_cmd, unittest_log, env=env, header=header) else "FAIL"
        results["python_unittest"] = status
        results["steps"].append({
             "name": "Python Unit Tests",
             "status": status,
             "log": "unit_tests/python/test_python_unittest.log",
             "details": "Discovered and ran tests in /tests directory"
        })

        # 2. Codegen Tests
        codegen_cmd = [sys.executable, "-m", "unittest", "tools.codegen.tests.test_codegen", "-v"]
        header_codegen = f"=== FUSION CODEGEN UNIT TEST ===\nCommand: {' '.join(codegen_cmd)}\nPWD: {os.getcwd()}\n================================\n\n"
        
        codegen_log = os.path.join(log_dir, "test_codegen.log")
        status = "PASS" if self._run_and_tee(codegen_cmd, codegen_log, env=env, header=header_codegen) else "FAIL"
        results["python_codegen"] = status
        results["steps"].append({
             "name": "Python Codegen Tests",
             "status": status,
             "log": "unit_tests/python/test_codegen.log",
             "details": "Verified Python bindings generation"
        })

        # 3. Pytest (Cross Language)
        cross_lang_log_dir = os.path.join(self.reporter.raw_logs_dir, "cross_language")
        os.makedirs(cross_lang_log_dir, exist_ok=True)
        env["FUSION_LOG_DIR"] = cross_lang_log_dir
        
        try:
             pytest_cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
             marker_expr = self._build_pytest_marker_expr()
             if marker_expr:
                 pytest_cmd.extend(["-m", marker_expr])
             
             header_pytest = f"=== FUSION PYTEST ===\nCommand: {' '.join(pytest_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\nMarker: {marker_expr}\n=====================\n\n"
             
             pytest_log = os.path.join(cross_lang_log_dir, "test_python_pytest.log")
             if self._run_and_tee(pytest_cmd, pytest_log, env=env, header=header_pytest):
                 status = "PASS"
             else:
                 status = "FAIL"
                 # Dump application-specific integration logs on failure
                 for app_log in ["cpp_integration.log", "rust_integration.log", "python_integration.log"]:
                     log_path_app = os.path.join(cross_lang_log_dir, app_log)
                     if os.path.exists(log_path_app):
                         print(f"\n--- COMPONENT LOG: {app_log} ---")
                         try:
                             with open(log_path_app, "r", encoding='utf-8', errors='ignore') as log_f:
                                 print(log_f.read())
                         except Exception as e:
                             print(f"Error reading {app_log}: {e}")
                         print(f"--- END COMPONENT LOG ---")
             
             results["python_integration"] = status
             results["steps"].append({
                 "name": "Cross-Language Integration Tests (Pytest)",
                 "status": status,
                 "log": "cross_language/test_python_pytest.log",
                 "details": "Ran test_cross_language.py"
             })
        except Exception as e:
             results["python_integration"] = f"SKIPPED (pytest error: {e})"
             print(f"Pytest execution error: {e}")

        return results

    def _run_cpp_tests(self):
        # C++
        log_dir = os.path.join(self.reporter.raw_logs_dir, "unit_tests", "cpp")
        os.makedirs(log_dir, exist_ok=True)
        cpp_log = os.path.join(log_dir, "test_cpp.log")

        cpp_exe = self._get_cpp_binary_path("cpp_test")
        if cpp_exe:
            cpp_cmd = [cpp_exe]
            header = f"=== FUSION C++ TEST ===\nCommand: {cpp_exe}\nPWD: {os.getcwd()}\n=======================\n\n"
            if self._run_and_tee(cpp_cmd, cpp_log, header=header):
                return "PASS"
            else:
                return "FAIL"
        else:
             return "SKIPPED"

    def _run_js_tests(self):
        log_dir = os.path.join(self.reporter.raw_logs_dir, "unit_tests", "js")
        os.makedirs(log_dir, exist_ok=True)
        js_log = os.path.join(log_dir, "test_js.log")

        npm_bin = "npm.cmd" if os.name == "nt" else "npm"
        # JS tests are run via npm script "test"
        # We can try to tee this too, but we need correct CWD
        cmd = [npm_bin, "test"]
        cwd = "src/js"
        # Since npm might be shell script on linux, subprocess works but better check
        # On windows "npm.cmd" works directly.
        
        # Note: npm test usually outputs a lot.
        header = f"=== FUSION JS TEST ===\nCommand: {' '.join(cmd)}\nPWD: {os.path.join(os.getcwd(), cwd)}\n======================\n\n"
        if self._run_and_tee(cmd, js_log, cwd=cwd, header=header):
            return "PASS"
        else:
            return "FAIL"


    def _run_demo_pytest(self, test_file, log_name, description):
        """Helper to run a demo via pytest and capture results."""
        results = {"steps": []}
        log_dir = os.path.join(self.reporter.raw_logs_dir, "demos", log_name)
        os.makedirs(log_dir, exist_ok=True)
        
        env = os.environ.copy()
        # Ensure project modules and generated bindings are in path
        env["PYTHONPATH"] = os.pathsep.join([
            os.getcwd(),
            os.path.join(os.getcwd(), "src/python"),
            os.path.join(os.getcwd(), "build/generated/python")
        ])
        env["FUSION_LOG_DIR"] = log_dir
        
        pytest_cmd = [sys.executable, "-m", "pytest", test_file, "-v"]
        marker_expr = self._build_pytest_marker_expr()
        if marker_expr:
            pytest_cmd.extend(["-m", marker_expr])
        
        log_path = os.path.join(log_dir, "pytest.log")
        header = f"=== FUSION DEMO PYTEST: {description} ===\nCommand: {' '.join(pytest_cmd)}\nPWD: {os.getcwd()}\n========================================\n\n"
        
        success = self._run_and_tee(pytest_cmd, log_path, env=env, header=header)
        status = "PASS" if success else "FAIL"
        
        results["steps"].append({
            "name": description,
            "status": status,
            "log": f"demos/{log_name}/pytest.log",
            "details": f"Executed integration tests for {description}"
        })
        return status, results

    def run_demos(self, demo_filter="all"):
        print("\n--- Running Integration Demos (via Pytest) ---")
        
        all_results = {"steps": []}
        
        # Mapping of demo names to their test files
        demo_map = {
            "simple": ("tests/test_simple_demo.py", "simple_demo", "Simple UDP Demo"),
            "integrated": ("tests/test_cross_language.py", "integrated_apps", "Integrated Apps Demo"),
            "pubsub": ("tests/test_pubsub_full.py", "automotive_pubsub", "Automotive Pub-Sub Demo"),
            "someipy": ("tests/test_someipy_interop.py", "someipy_interop", "someipy Interop Demo")
        }
        
        demos_to_run = []
        if demo_filter == "all":
            demos_to_run = ["simple", "integrated", "pubsub", "someipy"]
        else:
            # Handle comma-separated or single
            for d in demo_filter.replace(",", " ").split():
                if d in demo_map:
                    demos_to_run.append(d)
                else:
                    print(f"Warning: Unknown demo '{d}'")

        overall_pass = True
        for d in demos_to_run:
            test_file, log_name, desc = demo_map[d]
            print(f"\n>> Running Demo: {desc}")
            status, res = self._run_demo_pytest(test_file, log_name, desc)
            all_results["steps"].extend(res["steps"])
            if status != "PASS":
                overall_pass = False
        
        all_results["demo_status"] = "PASS" if overall_pass and demos_to_run else "FAIL"
        if not demos_to_run:
             all_results["demo_status"] = "SKIPPED"

        return all_results
        

if __name__ == "__main__":
    import sys
    import os
    # Ensure project root is in sys.path
    sys.path.append(os.getcwd())

    import argparse
    parser = argparse.ArgumentParser(description="Fusion Test Runner")
    parser.add_argument("--test-filter", default="all", help="Filter for unit tests (rust, python, cpp, js, all)")
    parser.add_argument("--demos", default="none", help="Run demos (simple, integrated, pubsub, someipy, all)")
    parser.add_argument("--skip-unit", action="store_true", help="Skip unit tests")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts before running")
    
    args = parser.parse_args()
    
    env = get_environment()
    reporter = TestReporter(os.getcwd())
    
    # Initialize builder (dummy for now as we invoke builds directly or assume pre-built)
    builder = None 
    
    tester = Tester(reporter, builder, env_caps=env.to_dict())
    
    if not args.skip_unit:
        tester.run_unit_tests()
        
    if args.demos != "none":
        tester.run_demos(args.demos)
