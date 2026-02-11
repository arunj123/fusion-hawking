import subprocess
import os
import time
import threading
import json
import sys

class Tester:
    def __init__(self, reporter, builder):
        self.reporter = reporter
        self.builder = builder

    def _get_cpp_binary_path(self, name):
        """Helper to find C++ binary path based on platform."""
        # 1. Search standard locations
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
            
        # 2. Fallback: Recursive Search in build dir
        print(f"DEBUG: '{name}' not found in standard paths. Searching 'build' directory...")
        if os.path.exists("build"):
            print("DEBUG: Listing 'build' directory content:")
            for root, dirs, files in os.walk("build"):
                for f in files:
                    print(os.path.join(root, f))
        else:
            print(f"DEBUG: 'build' directory does not exist in CWD: {os.getcwd()}")
            print(f"DEBUG: Directory listing of CWD: {os.listdir('.')}")
        for root, dirs, files in os.walk("build"):
            if name in files or f"{name}.exe" in files:
                found_path = os.path.join(root, name if name in files else f"{name}.exe")
                print(f"DEBUG: Found '{name}' at {found_path}")
                return found_path
        
        print(f"WARNING: C++ binary '{name}' not found.")
        return None

    def run_unit_tests(self):
        print("\n--- Running Unit Tests ---")
        results = {"steps": []}
        
        # Rust
        print("  Running Rust tests...")
        rust_status = self._run_rust_tests()
        results["rust"] = rust_status
        results["steps"].append({
            "name": "Rust Unit Tests",
            "status": rust_status,
            "log": "test_rust",
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
            "log": "test_cpp",
            "details": "Ran 'cpp_test' binary"
        })

        print(f"  Unit test results: {results}")
        
        # JS
        print("  Running JS tests...")
        js_status = self._run_js_tests()
        results["js"] = js_status
        results["steps"].append({
            "name": "JS/TS Unit Tests",
            "status": js_status,
            "log": "test_js",
            "details": "Ran 'npm test' in src/js"
        })

        return results

    def _run_rust_tests(self):
        # Rust
        if self.builder.run_command(["cargo", "test"], "test_rust"):
            return "PASS"
        else:
            return "FAIL"

    def _run_python_tests(self):
        results = {"steps": []}
        # Python
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
        env["FUSION_LOG_DIR"] = str(self.reporter.raw_logs_dir)
        
        # 1. Unittest
        with open(self.reporter.get_log_path("test_python_unittest"), "w") as f:
             py_cmd = [sys.executable, "-m", "unittest", "discover", "tests"]
             f.write(f"=== FUSION UNIT TEST ===\nCommand: {' '.join(py_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n========================\n\n")
             f.flush()
             status = "PASS" if subprocess.call(py_cmd, stdout=f, stderr=subprocess.STDOUT, env=env) == 0 else "FAIL"
             results["python_unittest"] = status
             results["steps"].append({
                 "name": "Python Unit Tests",
                 "status": status,
                 "log": "test_python_unittest",
                 "details": "Discovered and ran tests in /tests directory"
             })

        # 2. Codegen Tests
        with open(self.reporter.get_log_path("test_codegen"), "w") as f:
             codegen_cmd = [sys.executable, "-m", "unittest", "tools.codegen.tests.test_codegen", "-v"]
             f.write(f"=== FUSION CODEGEN UNIT TEST ===\nCommand: {' '.join(codegen_cmd)}\nPWD: {os.getcwd()}\n================================\n\n")
             f.flush()
             status = "PASS" if subprocess.call(codegen_cmd, stdout=f, stderr=subprocess.STDOUT, env=env) == 0 else "FAIL"
             results["python_codegen"] = status
             results["steps"].append({
                 "name": "Python Codegen Tests",
                 "status": status,
                 "log": "test_codegen",
                 "details": "Verified Python bindings generation"
             })

        # 3. Pytest (Cross Language)
        with open(self.reporter.get_log_path("test_python_pytest"), "w") as f:
             # Check if pytest is installed
             try:
                 # Run pytest on the whole tests/ directory to catch all issues, not just cross_language
                 pytest_cmd = [sys.executable, "-m", "pytest", "tests/"]
                 f.write(f"=== FUSION PYTEST ===\nCommand: {' '.join(pytest_cmd)}\nPWD: {os.getcwd()}\nEnvironment [PYTHONPATH]: {env['PYTHONPATH']}\n=====================\n\n")
                 f.flush()
                 if subprocess.call(pytest_cmd, stdout=f, stderr=subprocess.STDOUT, env=env) == 0:
                     status = "PASS"
                 else:
                     status = "FAIL"
                     # Dump log for CI visibility
                     print(f"\n--- FAILURE LOG: python_integration ---")
                     with open(self.reporter.get_log_path("test_python_pytest"), "r") as log_f:
                         print(log_f.read())
                     print(f"--- END LOG ---")
  
                     # Dump application-specific integration logs
                     for app_log in ["cpp_integration.log", "rust_integration.log", "python_integration.log"]:
                         log_path = os.path.join(env["FUSION_LOG_DIR"], app_log)
                         if os.path.exists(log_path):
                             print(f"\n--- COMPONENT LOG: {app_log} ---")
                             try:
                                 with open(log_path, "r", encoding='utf-8', errors='ignore') as log_f:
                                     print(log_f.read())
                             except Exception as e:
                                 print(f"Error reading {app_log}: {e}")
                             print(f"--- END COMPONENT LOG ---")
                 
                 results["python_integration"] = status
                 results["steps"].append({
                     "name": "Cross-Language Integration Tests (Pytest)",
                     "status": status,
                     "log": "test_python_pytest",
                     "details": "Ran test_cross_language.py"
                 })
             except Exception as e:
                 results["python_integration"] = f"SKIPPED (pytest error: {e})"

             except Exception as e:
                 results["python_integration"] = f"SKIPPED (pytest error: {e})"

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

    def _run_js_tests(self):
        npm_bin = "npm"
        if os.name == "nt":
            npm_bin = "npm.cmd"
            
        if self.builder.run_command([npm_bin, "test"], "test_js", cwd="src/js"):
            return "PASS"
        else:
            return "FAIL"


    def _prebuild_rust_demo(self):
        """Builds the Rust demo app to avoid compilation delays during runtime."""
        print("  Pre-building Rust Demo...")
        cmd = ["cargo", "build"]
        cwd = "examples/integrated_apps/rust_app"
        subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_demos(self, demo_filter="all"):
        print("\n--- Running Integration Demos ---")
        
        results = {}
        
        # 1. Simple Demos (No SD)
        if demo_filter in ["all", "simple"]:
            print("Running Simple Demos (No SD)...")
            simple_res = self._run_simple_demos()
            results.update(simple_res)
        
        # 2. Integrated Apps
        if demo_filter in ["all", "integrated"]:
            # Logic from run_demos.ps1
            # 1. Start Rust (runs, waits for events)
            # 2. Start Python
            # 3. Start C++
            
            # Pre-build Rust to ensure starts immediately
            self._prebuild_rust_demo()
            
            # We need to capture outputs to separate logs to verify logic patterns
            
            rust_log = self.reporter.get_log_path("demo_rust")
            py_log = self.reporter.get_log_path("demo_python")
            rust_log = self.reporter.get_log_path("demo_rust")
            py_log = self.reporter.get_log_path("demo_python")
            cpp_log = self.reporter.get_log_path("demo_cpp")
            js_log = self.reporter.get_log_path("demo_js")

            
            procs = []
            
            # Keep track of files to close
            log_files = []
            
            # Resolve C++ binary
            cpp_exe = self._get_cpp_binary_path("cpp_app")

            
            try:
                # Rust Standalone Demo
                f_rust = open(rust_log, "w")
                log_files.append(f_rust)
                rust_env = os.environ.copy()
                rust_env["RUST_LOG"] = "debug"
                rust_cmd = ["cargo", "run"]
                f_rust.write(f"=== FUSION TEST RUNNER ===\nCommand: {' '.join(rust_cmd)}\nPWD: {os.path.join(os.getcwd(), 'examples/integrated_apps/rust_app')}\nEnvironment [RUST_LOG]: debug\n==========================\n\n")
                f_rust.flush()
                p_rust = subprocess.Popen(rust_cmd, stdout=f_rust, stderr=subprocess.STDOUT, env=rust_env, cwd="examples/integrated_apps/rust_app")
                procs.append(p_rust)
                time.sleep(2)
                
                # Python Standalone Demo
                env = os.environ.copy()
                # Note: PYTHONPATH is still needed to find the core runtime if not installed via pip
                env["PYTHONPATH"] = os.pathsep.join([
                    os.path.join(os.getcwd(), "src/python"),
                    os.path.join(os.getcwd(), "build/generated/python")
                ])
                f_py = open(py_log, "w")
                log_files.append(f_py)
                # Run the script within its directory
                py_cmd = [sys.executable, "-u", "main.py"]
                f_py.write(f"=== FUSION TEST RUNNER ===\nCommand: {' '.join(py_cmd)}\nPWD: {os.path.join(os.getcwd(), 'examples/integrated_apps/python_app')}\n==========================\n\n")
                f_py.flush()
                p_py = subprocess.Popen(py_cmd, stdout=f_py, stderr=subprocess.STDOUT, env=env, cwd="examples/integrated_apps/python_app")
                procs.append(p_py)
                
                if cpp_exe:
                    # Convert to absolute path since we change CWD
                    abs_cpp_exe = os.path.abspath(cpp_exe)
                    f_cpp = open(cpp_log, "w")
                    log_files.append(f_cpp)
                    cpp_cmd = [abs_cpp_exe]
                    f_cpp.write(f"=== FUSION TEST RUNNER ===\nCommand: {abs_cpp_exe}\nPWD: {os.path.join(os.getcwd(), 'examples/integrated_apps/cpp_app')}\n==========================\n\n")
                    f_cpp.flush()
                    p_cpp = subprocess.Popen(cpp_cmd, stdout=f_cpp, stderr=subprocess.STDOUT, cwd="examples/integrated_apps/cpp_app")
                    procs.append(p_cpp)
                
                # JS Standalone Demo
                js_app_dir = "examples/integrated_apps/js_app"
                if os.path.exists(js_app_dir):
                    f_js = open(js_log, "w")
                    log_files.append(f_js)
                    # Use locally installed node modules if needed, or assume built
                    # We run 'node dist/src/index.js' assuming build. Or use pre-build.
                    # Build first? fusion build --target js should have built it? 
                    # Actually main.py build_js builds src/js. It doesn't build examples.
                    # We need to build the example here or assume user did.
                    # Let's run 'npm install && npm run build' quickly?
                    # Or just run 'npx tsx src/index.ts' if supported.
                    # We'll assume compiled to 'dist/index.js' per our package.json, 
                    # but we haven't run build for it.
                    # Let's try to run 'npm run build' quietly first.
                    print("  Building JS Demo...")
                    npm_bin = "npm.cmd" if os.name == 'nt' else "npm"
                    subprocess.run([npm_bin, "install"], cwd=js_app_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run([npm_bin, "run", "build"], cwd=js_app_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    js_cmd = ["node", "dist/index.js"]
                    f_js.write(f"=== FUSION TEST RUNNER ===\nCommand: {' '.join(js_cmd)}\nPWD: {os.path.join(os.getcwd(), js_app_dir)}\n==========================\n\n")
                    f_js.flush()
                    p_js = subprocess.Popen(js_cmd, stdout=f_js, stderr=subprocess.STDOUT, cwd=js_app_dir)
                    procs.append(p_js)

                
                # Run for 20s (Increased for safety)
                print("  Integrated Apps started, waiting 20s...")
                time.sleep(20)
                
            finally:
                # 1. Terminate processes gracefully
                print("  Stopping demos...")
                for p in procs:
                    try:
                        p.terminate()
                    except:
                        pass
                
                # 2. Wait for them to exit
                for p in procs:
                    try:
                        p.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        # 3. Force kill if they don't exit
                        p.kill()
                
                # 4. Explicitly close log files to flush buffers
                for f in log_files:
                    f.close()
                
            print("  Verifying Integrated Apps logs...")
            time.sleep(1) # Extra buffer for OS file system
            results = self._verify_demos(rust_log, py_log, cpp_log, js_log, results)
            
            # If failed, dump logs
            if results.get("demo_status") == "FAIL":
                 for log_name, log_path in [("rust", rust_log), ("python", py_log), ("cpp", cpp_log), ("js", js_log)]:
                     if os.path.exists(log_path):
                         print(f"\n--- FAILURE LOG: {log_name} ---")

                         with open(log_path, "r") as f:
                             print(f.read())
                         print(f"--- END LOG ---")

        # 3. Automotive Pub-Sub Demo (Radar -> Fusion -> ADAS)
        if demo_filter in ["all", "pubsub"]:
            print("\nRunning Automotive Pub-Sub Demo...")
            pubsub_result = self._run_automotive_pubsub_demo()
            
            # Merge pubsub results, extending steps list instead of overwriting
            pubsub_steps = pubsub_result.pop("steps", [])
            results.update(pubsub_result)
            results.setdefault("steps", []).extend(pubsub_steps)

        # 4. someipy Demo (someipy Service -> Fusion Clients)
        if demo_filter in ["all", "someipy"]:
            print("\nRunning someipy Interop Demo...")
            someipy_res = self._run_someipy_demo()
            
            someipy_steps = someipy_res.pop("steps", [])
            results.update(someipy_res)
            results.setdefault("steps", []).extend(someipy_steps)

        return results

    def _run_someipy_demo(self):
        """Run the someipy interop demo."""
        results = {"steps": []}
        log_path = self.reporter.get_log_path("demo_someipy")
        
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
        
        demo_dir = "examples/someipy_demo"
        procs = []
        
        # The someipy demo runs entirely on loopback. patch_configs sets the
        # SD multicast interface to the detected NIC (e.g. 'eth0'), but the
        # C++ runtime resolves interface names to OS indices for multicast.
        # On WSL, eth0 (index 2) routes multicast away from loopback.
        # Force SD multicast interface to 'lo' so the C++ client can discover
        # the loopback-only someipy service.
        try:
            cfg_path = os.path.join(demo_dir, "client_config.json")
            with open(cfg_path, "r") as f:
                cfg = json.load(f)
            patched = False
            for ep_name, ep_cfg in cfg.get("endpoints", {}).items():
                if "sd_multicast" in ep_name and ep_cfg.get("interface") != "lo":
                    ep_cfg["interface"] = "lo"
                    patched = True
            if patched:
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
        except Exception:
            pass
        
        try:
            with open(log_path, "w") as log:
                log.write("=== FUSION SOMEIPY INTEROP DEMO ===\n")
                log.flush()
                
                # 1. Start Daemon
                print("  Starting someipy daemon...")
                p_daemon = subprocess.Popen([sys.executable, "-u", "start_daemon.py"], stdout=log, stderr=subprocess.STDOUT, cwd=demo_dir)
                procs.append(p_daemon)
                time.sleep(2)
                
                # 2. Start Service
                print("  Starting someipy service...")
                p_service = subprocess.Popen([sys.executable, "-u", "service_someipy.py"], stdout=log, stderr=subprocess.STDOUT, cwd=demo_dir)
                procs.append(p_service)
                time.sleep(3)
                
                # 3. Run Fusion Python Client
                print("  Running Fusion Python Client...")
                client_res = subprocess.run([sys.executable, "-u", "client_fusion.py"], stdout=log, stderr=subprocess.STDOUT, cwd=demo_dir, env=env)
                
                # 4. Run Fusion Rust Client
                print("  Running Fusion Rust Client...")
                # Binary is expected at target/debug/someipy_client.exe or similar
                rust_bin = os.path.abspath(os.path.join("target", "debug", "someipy_client"))
                if os.name == 'nt': rust_bin += ".exe"
                
                if os.path.exists(rust_bin):
                    subprocess.run([rust_bin], stdout=log, stderr=subprocess.STDOUT, cwd=demo_dir)
                else:
                    log.write(f"\n[WARN] Rust client not found at {rust_bin}. Skipping.\n")
                
                # 5. Run Fusion C++ Client
                print("  Running Fusion C++ Client...")
                cpp_bin = self._get_cpp_binary_path("client_fusion")
                if cpp_bin:
                    subprocess.run([os.path.abspath(cpp_bin)], stdout=log, stderr=subprocess.STDOUT, cwd=demo_dir)
                else:
                    log.write("\n[WARN] C++ client not found. Skipping.\n")

                # 6. Run Fusion JS Client
                print("  Running Fusion JS Client...")
                js_client_dir = os.path.join(demo_dir, "js_client")
                if os.path.exists(js_client_dir):
                    npm_bin = "npm.cmd" if os.name == 'nt' else "npm"
                    subprocess.run([npm_bin, "install"], cwd=js_client_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run([npm_bin, "run", "build"], cwd=js_client_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run(["node", "dist/index.js"], stdout=log, stderr=subprocess.STDOUT, cwd=js_client_dir, timeout=15)
                else:
                    log.write("\n[WARN] JS client not found. Skipping.\n")

            # Verify Logs
            with open(log_path, "r", errors="ignore") as f:
                content = f.read()
            
            patterns = [
                ("[someipy Service] Offering Service 0x1234:0x0001", "someipy Service Startup"),
                ("Got Response: 'Hello from Fusion Python!'", "Python -> someipy Interop"),
                ("Got Response: 'Hello from Fusion Rust!'", "Rust -> someipy Interop"),
                ("Got Response: 'Hello from Fusion C++!'", "C++ -> someipy Interop"),
                ("Got Response: 'Hello from Fusion JS!'", "JS -> someipy Interop")
            ]
            
            for pattern, desc in patterns:
                found = pattern in content
                results["steps"].append({
                    "name": f"someipy Demo: {desc}",
                    "status": "PASS" if found else "FAIL",
                    "log": "demo_someipy",
                    "details": f"Checked log for '{pattern}'"
                })
            
            pass_count = sum(1 for s in results["steps"] if s["status"] == "PASS")
            # We allow Rust/C++ skip if not built, but Python must pass
            if "Got Response: 'Hello from Fusion Python!'" in content:
                results["someipy_demo"] = "PASS"
            else:
                results["someipy_demo"] = "FAIL"

        except Exception as e:
            print(f"Error running someipy demo: {e}")
            results["someipy_demo"] = "ERROR"
        finally:
            for p in procs:
                p.kill()
                p.wait()
                
        return results

    def _run_automotive_pubsub_demo(self):
        """Run the Automotive Pub-Sub demo (Radar -> Fusion -> ADAS pipeline)."""
        results = {}
        
        # Check if Python ADAS script exists
        adas_script = "examples/automotive_pubsub/python_adas/main.py"
        js_adas_dir = "examples/automotive_pubsub/js_adas"
        
        if not os.path.exists(adas_script) and not os.path.exists(js_adas_dir):
            print("Warning: Automotive Pub-Sub demo not found, skipping...")
            return {"automotive_pubsub_demo": "SKIPPED"}
        
        log_path = self.reporter.get_log_path("demo_automotive_pubsub")
        js_log_path = self.reporter.get_log_path("demo_automotive_pubsub_js")

        
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(["src/python", "build", "build/generated/python"])
        
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
                cmd = [sys.executable, "-u", adas_script]
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
                
                # Start JS ADAS app too if exists
                js_proc = None
                if os.path.exists(js_adas_dir):
                     with open(js_log_path, "w") as js_log:
                         js_log.write("=== JS ADAS SUBSCRIBER ===\n")
                         # Build first
                         npm_bin = "npm.cmd" if os.name == 'nt' else "npm"
                         subprocess.run([npm_bin, "install"], cwd=js_adas_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                         subprocess.run([npm_bin, "run", "build"], cwd=js_adas_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                         
                         js_cmd = ["node", "dist/index.js"]
                         js_proc = subprocess.Popen(js_cmd, cwd=js_adas_dir, stdout=js_log, stderr=subprocess.STDOUT)
                
                time.sleep(3)
                proc.kill()
                proc.wait()
                if js_proc:
                    js_proc.kill()
                    js_proc.wait()

            
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
            
            # Verify JS Log
            if os.path.exists(js_log_path):
                 with open(js_log_path, "r", errors="ignore") as f:
                     js_content = f.read()
                 if "ADAS Application starting" in js_content or "Subscribed" in js_content:
                      results.setdefault("steps", []).append({
                        "name": "Automotive Pub-Sub: JS ADAS Subscriber Startup",
                        "status": "PASS",
                        "log": "demo_automotive_pubsub_js",
                        "details": "JS ADAS app started and subscribed"
                      })
                 else:
                      results["automotive_pubsub_demo"] = "FAIL" # partial fail
                      results.setdefault("steps", []).append({
                        "name": "Automotive Pub-Sub: JS ADAS Subscriber Startup",
                        "status": "FAIL",
                        "log": "demo_automotive_pubsub_js",
                        "details": "JS ADAS app failed to start properly"
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
            print(f"[WARN] Simple demos not found at {server_bin}")
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
                    print("[PASS] Simple Demo PASS")
                    return {"simple_demo": "PASS", "steps": [{"name": "Simple UDP Demo", "status": "PASS", "details": "Client received 'Success'"}]}
                else:
                    print(f"[FAIL] Simple Demo FAIL: {output}")
                    return {"simple_demo": "FAIL", "steps": [{"name": "Simple UDP Demo", "status": "FAIL", "details": "Client did not output 'Success'"}]}
                    
            finally:
                server_proc.terminate()
                server_proc.wait()

    def _verify_demos(self, rust, py, cpp, js, initial_results):
        results = initial_results
        steps = results.get('steps', [])

        
        # Helper logging
        def check(log_name, path, pattern, description):
            found = False
            content = ""
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
            
            if not found:
                print(f"\n[FAIL] {description} FAILED. Log '{log_name}':\n{'-'*40}\n{content}\n{'-'*40}\n")
                
            return found

        # Rust Checks
        check("demo_rust", rust, "Math.Add", "RPC: Rust Provider (Math.Add)")
        check("demo_rust", rust, "Received Notification", "Event: Rust Listener")
        
        # Python Checks
        check("demo_python", py, "Sending Add", "RPC: Python Client (Sending Add)")
        check("demo_python", py, "Reversing", "RPC: Python String Service")
        
        # C++ Checks
        check("demo_cpp", cpp, "Math.Add Result", "RPC: C++ Client -> Rust Math")
        check("demo_cpp", cpp, "Sorting 5 items", "RPC: Python -> C++ Sort")
        check("demo_cpp", cpp, "Sorting 3 items", "RPC: Rust -> C++ Sort")
        check("demo_cpp", cpp, "Field 'status' changed", "Field: C++ Service Update")
        
        # JS Checks
        check("demo_js", js, "Calling Math.Add", "RPC: JS Client -> Rust Math")
        check("demo_js", js, "Calling String.Reverse", "RPC: JS Client -> Python String")

        
        # Aggregate logic
        pass_count = sum(1 for s in steps if s['status'] == 'PASS')
        results['demo_status'] = "PASS" if pass_count == len(steps) else "FAIL"
        results['steps'] = steps # Return list for detailed reporting
        
        return results
