import subprocess
import os
import time
import threading

class Tester:
    def __init__(self, reporter, builder):
        self.reporter = reporter
        self.builder = builder

    def _get_cpp_binary_path(self, name):
        """Helper to find C++ binary path based on platform."""
        if os.name == 'nt':
            # Windows: Check build/Release/name.exe
            path = os.path.join("build", "Release", f"{name}.exe")
            if os.path.exists(path): return path
            # Also check build/name.exe (if built without Release subdir)
            path = os.path.join("build", f"{name}.exe")
            if os.path.exists(path): return path
        else:
            # Linux/macOS: Check build/name
            path = os.path.join("build", name)
            if os.path.exists(path): return path
            # Also check build_linux (used in manual WSL tests)
            path = os.path.join("build_linux", name)
            if os.path.exists(path): return path
            
        return None

    def run_unit_tests(self):
        print("\n--- Running Unit Tests ---")
        results = {}
        print("  Running Rust tests...")
        results["rust"] = self._run_rust_tests()
        print("  Running Python tests...")
        results.update(self._run_python_tests())
        print("  Running C++ tests...")
        results["cpp"] = self._run_cpp_tests()
        print(f"  Unit test results: {results}")
        return results

    def _run_rust_tests(self):
        # Rust
        if self.builder.run_command(["cargo", "test"], "test_rust"):
            return "PASS"
        else:
            return "FAIL"

    def _run_python_tests(self):
        results = {}
        # Python
        env = os.environ.copy()
        env["PYTHONPATH"] = "src/python;build;build/generated/python"
        env["FUSION_LOG_DIR"] = self.reporter.raw_logs_dir
        
        # 1. Unittest
        with open(self.reporter.get_log_path("test_python_unittest"), "w") as f:
             py_cmd = ["python", "-m", "unittest", "discover", "tests"]
             f.write(f"=== FUSION UNIT TEST ===\nCommand: {' '.join(py_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n========================\n\n")
             f.flush()
             if subprocess.call(py_cmd, stdout=f, stderr=subprocess.STDOUT, env=env) == 0:
                 results["python_unittest"] = "PASS"
             else:
                 results["python_unittest"] = "FAIL"

        # 2. Codegen Tests
        with open(self.reporter.get_log_path("test_codegen"), "w") as f:
             codegen_cmd = ["python", "-m", "unittest", "tools.codegen.tests.test_codegen", "-v"]
             f.write(f"=== FUSION CODEGEN UNIT TEST ===\nCommand: {' '.join(codegen_cmd)}\nPWD: {os.getcwd()}\n================================\n\n")
             f.flush()
             if subprocess.call(codegen_cmd, stdout=f, stderr=subprocess.STDOUT, env=env) == 0:
                 results["python_codegen"] = "PASS"
             else:
                 results["python_codegen"] = "FAIL"

        # 3. Pytest (Cross Language)
        with open(self.reporter.get_log_path("test_python_pytest"), "w") as f:
             # Check if pytest is installed
             try:
                 pytest_cmd = ["python", "-m", "pytest", "tests/test_cross_language.py"]
                 f.write(f"=== FUSION PYTEST ===\nCommand: {' '.join(pytest_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n=====================\n\n")
                 f.flush()
                 if subprocess.call(pytest_cmd, stdout=f, stderr=subprocess.STDOUT, env=env) == 0:
                     results["python_integration"] = "PASS"
                 else:
                     results["python_integration"] = "FAIL"
             except:
                 results["python_integration"] = "SKIPPED (pytest missing)"
        return results

    def _run_cpp_tests(self):
        # C++
        cpp_exe = self._get_cpp_binary_path("cpp_test")
        if cpp_exe:
            cpp_cmd = [cpp_exe]
            with open(self.reporter.get_log_path("test_cpp"), "w") as f:
                 f.write(f"=== FUSION C++ TEST ===\nCommand: {cpp_exe}\nPWD: {os.getcwd()}\n=======================\n\n")
                 f.flush()
                 if subprocess.call(cpp_cmd, stdout=f, stderr=subprocess.STDOUT) == 0:
                     return "PASS"
                 else:
                     return "FAIL"
        else:
             return "SKIPPED"

    def run_demos(self):
        print("\n--- Running Integration Demos ---")
        
        results = {}
        
        # 1. Simple Demos (No SD) - mimicking legacy run_demos.ps1
        print("Running Simple Demos (No SD)...")
        simple_res = self._run_simple_demos()
        results.update(simple_res)
        
        # 2. Integrated Apps
        # Logic from run_demos.ps1
        # 1. Start Rust (runs, waits for events)
        # 2. Start Python
        # 3. Start C++
        
        # We need to capture outputs to separate logs to verify logic patterns
        
        rust_log = self.reporter.get_log_path("demo_rust")
        py_log = self.reporter.get_log_path("demo_python")
        cpp_log = self.reporter.get_log_path("demo_cpp")
        
        procs = []
        
        try:
            # Rust
            f_rust = open(rust_log, "w")
            rust_cmd = ["cargo", "run", "--example", "rust_app"]
            f_rust.write(f"=== FUSION TEST RUNNER ===\nCommand: {' '.join(rust_cmd)}\nPWD: {os.getcwd()}\n==========================\n\n")
            f_rust.flush()
            p_rust = subprocess.Popen(rust_cmd, stdout=f_rust, stderr=subprocess.STDOUT)
            procs.append(p_rust)
            time.sleep(2)
            
            # Python
            env = os.environ.copy()
            env["PYTHONPATH"] = "src/python;build;build/generated/python"
            f_py = open(py_log, "w")
            py_cmd = ["python", "-u", "examples/integrated_apps/python_app/main.py"]
            f_py.write(f"=== FUSION TEST RUNNER ===\nCommand: {' '.join(py_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n==========================\n\n")
            f_py.flush()
            p_py = subprocess.Popen(py_cmd, stdout=f_py, stderr=subprocess.STDOUT, env=env)
            procs.append(p_py)
            
            # C++
            cpp_exe = self._get_cpp_binary_path("cpp_app")
            if cpp_exe:
                f_cpp = open(cpp_log, "w")
                cpp_cmd = [cpp_exe]
                f_cpp.write(f"=== FUSION TEST RUNNER ===\nCommand: {cpp_exe}\nPWD: {os.getcwd()}\n==========================\n\n")
                f_cpp.flush()
                p_cpp = subprocess.Popen(cpp_cmd, stdout=f_cpp, stderr=subprocess.STDOUT)
                procs.append(p_cpp)
            
            # Run for 10s
            print("  Integrated Apps started, waiting 10s...")
            time.sleep(10)
            
        finally:
            for p in procs:
                p.kill() # Force kill
            
        print("  Verifying Integrated Apps logs...")
        results = self._verify_demos(rust_log, py_log, cpp_log, results)

        # 3. Automotive Pub-Sub Demo (Radar -> Fusion -> ADAS)
        print("\nRunning Automotive Pub-Sub Demo...")
        pubsub_result = self._run_automotive_pubsub_demo()
        
        # Merge pubsub results, extending steps list instead of overwriting
        pubsub_steps = pubsub_result.pop("steps", [])
        results.update(pubsub_result)
        results.setdefault("steps", []).extend(pubsub_steps)

        return results

    def _run_automotive_pubsub_demo(self):
        """Run the Automotive Pub-Sub demo (Radar -> Fusion -> ADAS pipeline)."""
        results = {}
        
        # Check if Python ADAS script exists
        adas_script = "examples/automotive_pubsub/python_adas/main.py"
        if not os.path.exists(adas_script):
            print("Warning: Automotive Pub-Sub demo not found, skipping...")
            return {"automotive_pubsub_demo": "SKIPPED"}
        
        log_path = self.reporter.get_log_path("demo_automotive_pubsub")
        
        env = os.environ.copy()
        env["PYTHONPATH"] = "src/python;build;build/generated/python"
        
        try:
            with open(log_path, "w") as log:
                log.write("=== FUSION AUTOMOTIVE PUB-SUB DEMO ===\n")
                log.write(f"Script: {adas_script}\n")
                log.write("Pattern: Radar (C++) -> Fusion (Rust) -> ADAS (Python)\n")
                log.write("Note: Full demo requires all 3 apps running.\n")
                log.write("This test validates Python ADAS subscriber startup.\n")
                log.write("======================================\n\n")
                log.flush()
                
                # Run Python ADAS app for 3 seconds to verify startup
                cmd = ["python", "-u", adas_script]
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
                time.sleep(3)
                proc.kill()
                proc.wait()
            
            # Read log to verify startup patterns
            with open(log_path, "r", errors="ignore") as f:
                content = f.read()
            
            if "ADAS Application" in content or "Subscribed" in content:
                print("OK: Automotive Pub-Sub Demo: ADAS startup verified")
                results["automotive_pubsub_demo"] = "PASS"
                results.setdefault("steps", []).append({
                    "name": "Automotive Pub-Sub: ADAS Subscriber Startup",
                    "status": "PASS",
                    "log": "demo_automotive_pubsub",
                    "details": "Python ADAS app started and subscribed to FusionService"
                })
            else:
                print("FAIL: Automotive Pub-Sub Demo: ADAS startup failed")
                results["automotive_pubsub_demo"] = "FAIL"
                results.setdefault("steps", []).append({
                    "name": "Automotive Pub-Sub: ADAS Subscriber Startup",
                    "status": "FAIL",
                    "log": "demo_automotive_pubsub",
                    "details": "Failed to detect ADAS application startup"
                })
                
        except Exception as e:
            print(f"Warning: Automotive Pub-Sub Demo error: {e}")
            results["automotive_pubsub_demo"] = "ERROR"
        
        return results

    def _run_simple_demos(self):
        # Runs basic client/server without Service Discovery
        server_bin = "target/debug/simple_server.exe"
        client_bin = "target/debug/simple_client.exe"
        
        # Windows extension check
        if os.name != 'nt':
            server_bin = server_bin.replace(".exe", "")
            client_bin = client_bin.replace(".exe", "")

        if not os.path.exists(server_bin) or not os.path.exists(client_bin):
            print(f"⚠️ Simple demos not found at {server_bin}")
            return {"simple_demo": "SKIPPED"}
            
        print(f"Starting {server_bin}...")
        log_path = self.reporter.get_log_path("demo_simple")
        
        with open(log_path, "w") as log:
            # Start Server
            server_cmd = [server_bin]
            log.write(f"=== FUSION SIMPLE DEMO RUNNER ===\nServer Command: {' '.join(server_cmd)}\n")
            server_proc = subprocess.Popen(server_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            
            try:
                # Run Client
                print(f"Running {client_bin}...")
                client_cmd = [client_bin]
                log.write(f"Client Command: {' '.join(client_cmd)}\nPWD: {os.getcwd()}\n=================================\n\n")
                log.flush()
                
                result = subprocess.run(client_cmd, capture_output=True, text=True)
                output = result.stdout + result.stderr
                log.write(output)
                
                # Verify
                if "Success" in output:
                    print("✅ Simple Demo PASS")
                    return {"simple_demo": "PASS", "steps": [{"name": "Simple UDP Demo", "status": "PASS", "details": "Client received 'Success'"}]}
                else:
                    print(f"❌ Simple Demo FAIL: {output}")
                    return {"simple_demo": "FAIL", "steps": [{"name": "Simple UDP Demo", "status": "FAIL", "details": "Client did not output 'Success'"}]}
                    
            finally:
                server_proc.terminate()
                server_proc.wait()

    def _verify_demos(self, rust, py, cpp, initial_results):
        results = initial_results
        steps = results.get('steps', [])
        
        # Helper logging
        def check(log_name, path, pattern, description):
            found = False
            if os.path.exists(path):
                with open(path, "r", errors="ignore") as f:
                    content = f.read()
                    found = pattern in content
            
            status = "PASS" if found else "FAIL"
            # Add to steps list for UI
            steps.append({
                "name": description,
                "status": status,
                "log": log_name,
                "details": f"Checked '{log_name}' for '{pattern}'"
            })
            return found

        # Rust Checks
        check("demo_rust", rust, "Math.Add", "RPC: Rust Provider (Math.Add)")
        check("demo_rust", rust, "Received Notification", "Event: Rust Listener")
        
        # Python Checks
        check("demo_python", py, "Sending Add", "RPC: Python Client (Sending Add)")
        check("demo_python", py, "Reversing", "RPC: Python String Service")
        
        # C++ Checks
        check("demo_cpp", cpp, "Math.Add Result:", "RPC: C++ Client -> Rust Math")
        check("demo_cpp", cpp, "Sorting 5 items", "RPC: Python -> C++ Sort")
        check("demo_cpp", cpp, "Sorting 3 items", "RPC: Rust -> C++ Sort")
        check("demo_cpp", cpp, "Field 'status' changed", "Field: C++ Service Update")
        
        # Aggregate logic
        pass_count = sum(1 for s in steps if s['status'] == 'PASS')
        results['demo_status'] = "PASS" if pass_count == len(steps) else "FAIL"
        results['steps'] = steps # Return list for detailed reporting
        
        return results
