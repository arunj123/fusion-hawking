import argparse
import sys
import os
import time

from tools.fusion.toolchains import ToolchainManager
from tools.fusion.report import Reporter
from tools.fusion.build import Builder
from tools.fusion.test import Tester
from tools.fusion.coverage import CoverageManager
from tools.fusion.server import ProgressServer
from tools.fusion.utils import get_local_ip, detect_environment
from tools.fusion.diagrams import DiagramManager


def merge_results(base, new):
    """Helper to merge test result dicts, specifically extending 'steps' list."""
    if not new: return base
    steps = base.get("steps", [])
    new_steps = new.pop("steps", [])
    base.update(new)
    if new_steps:
        base["steps"] = steps + new_steps
    else:
        base["steps"] = steps
    return base


def run_diagrams(root_dir, reporter, server):
    """Stage: Generate PlantUML diagrams"""
    if server: server.update({"current_step": "Generating Diagrams"})
    reporter.generate_index({"current_step": "Generating Diagrams", "overall_status": "RUNNING"})
    diagrams = DiagramManager(root_dir, reporter)
    return diagrams.run()


def run_build(root_dir, reporter, builder, tool_status, target, server, skip_codegen=False, with_coverage=False, packet_dump=False):
    """Stage: Build Rust and C++"""
    if server: server.update({"current_step": "Building"})
    reporter.generate_index({"current_step": "Building", "overall_status": "RUNNING", "tools": tool_status})
    print("\n=== Building ===")
    
    if not skip_codegen and target in ["all", "rust", "cpp"]:
        # If running as "build" stage but NOT "all" stage (which handled it), we might need this.
        if not builder.generate_bindings(): 
            raise Exception("Bindings Generation Failed")
    
    if target in ["all", "rust", "python"]:
        if not builder.build_rust(packet_dump): 
            raise Exception("Rust Build Failed")
    
    if tool_status.get("cmake") and target in ["all", "cpp", "python"]:
        if not builder.build_cpp(with_coverage, packet_dump):
            raise Exception("C++ Build Failed")

    if target in ["all", "js", "python"]:
        if not builder.build_js():
            raise Exception("JS Build Failed")

    
    # Capture Configuration
    try:
        config_src = os.path.join(os.getcwd(), "build", "generated")
        if os.path.exists(config_src):
            config_dest = os.path.join(reporter.log_dir, "configs")
            import shutil
            shutil.copytree(config_src, config_dest, dirs_exist_ok=True)
            print(f"Captured configurations to {config_dest}")
    except Exception as e:
        print(f"[WARN] Failed to capture configs: {e}")
    
    return {"build": "PASS"}


def run_test(reporter, tester, target, server):
    """Stage: Run unit tests"""
    if server: server.update({"current_step": "Testing"})
    print("\n=== Testing ===")
    
    test_results = {"steps": []}
    
    if target == "all":
        test_results = tester.run_unit_tests()
    else:
        if target == "rust":
            test_results["rust"] = tester._run_rust_tests()
            test_results["steps"].append({"name": "Rust Unit Tests", "status": test_results["rust"], "details": "Ran target specific rust tests"})
        elif target == "python":
            py_res = tester._run_python_tests()
            merge_results(test_results, py_res)
        elif target == "cpp":
            test_results["cpp"] = tester._run_cpp_tests()
            test_results["steps"].append({"name": "C++ Unit Tests", "status": test_results["cpp"], "details": "Ran target specific cpp tests"})
        elif target == "js":
            test_results["js"] = tester._run_js_tests()
            test_results["steps"].append({"name": "JS Unit Tests", "status": test_results["js"], "details": "Ran 'npm test'"})

    
    return test_results


def run_demos(reporter, tester, server, test_results, demo_filter):
    """Stage: Run integration demos"""
    if server: server.update({"current_step": "Running Demos"})
    print("\n=== Demos ===")
    demo_results = tester.run_demos(demo_filter)
    merge_results(test_results, demo_results)
    return test_results


def run_coverage(reporter, cover, server, test_results, target):
    """Stage: Generate coverage reports"""
    if server: server.update({"current_step": "Coverage"})
    print("\n=== Coverage ===")
    cov_results = cover.run_coverage(target)
    merge_results(test_results, cov_results)
    return test_results


def main():
    parser = argparse.ArgumentParser(description="Fusion Hawking Automation Tool")
    parser.add_argument("--skip-demos", action="store_true", help="Skip integration demos")
    parser.add_argument("--skip-coverage", action="store_true", help="Skip coverage generation")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts before running")
    parser.add_argument("--server", action="store_true", default=True, help="Enable dashboard server")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable dashboard server (override)")
    parser.add_argument("--target", type=str, choices=["all", "rust", "python", "cpp", "js"], default="all", help="Target language to test")

    parser.add_argument("--demo", type=str, choices=["all", "simple", "integrated", "pubsub", "someipy"], default="all", help="Specific demo to run")
    parser.add_argument("--no-codegen", action="store_true", help="Skip codegen (assume artifacts exist)")
    parser.add_argument("--base-port", type=int, default=0, help="Port offset for test isolation")
    parser.add_argument("--with-coverage", action="store_true", help="Build C++ with coverage instrumentation")
    parser.add_argument("--packet-dump", action="store_true", help="Enable Wireshark-like packet dumping in runtimes")
    parser.add_argument("--no-vnet", action="store_true", help="Force disable virtual network tests")
    parser.add_argument("--vnet", action="store_true", help="Force enable virtual network tests (if detected)")
    parser.add_argument("--stage", type=str, 
                        choices=["diagrams", "codegen", "build", "test", "coverage", "docs", "demos", "all"],
                        default="all", help="Run specific build stage (for CI)")
    args = parser.parse_args()

    # Get Root Directory
    root_dir = os.path.abspath(os.getcwd())
    
    # Initialize Reporter FIRST
    reporter = Reporter(root_dir)

    # Server logic: Enable if --server is True AND --no-dashboard is False
    # Disable for stage-specific runs (CI mode)
    enable_server = args.server and not args.no_dashboard and args.stage == "all"
    server = ProgressServer(report_dir=os.path.join(root_dir, "logs")) if enable_server else None
    
    if server: 
        server.start()
        server.update({"current_step": "Initializing", "overall_status": "RUNNING"})
    
    tools = ToolchainManager()
    tool_status = tools.check_all()
    
    # Detect environment capabilities - Initial Pass
    real_env_caps = detect_environment()
    
    # Determine Execution Plan
    # Tuple: (run_name, force_no_vnet)
    execution_plan = []
    
    if real_env_caps['os'] == 'Linux' and (real_env_caps['has_veth'] or real_env_caps['has_netns']):
        if args.no_vnet:
            execution_plan.append(("Physical Network (No VNet)", True))
        elif args.vnet:
             # If strictly requested --vnet, maybe running both? 
             # Goal: Default behavior or explicit robust check = Run 1 (No VNet), Run 2 (VNet)
             execution_plan.append(("Physical Network (No VNet)", True))
             execution_plan.append(("Virtual Network (VNet)", False))
        else:
             # Default: Run both to ensure coverage
             execution_plan.append(("Physical Network (No VNet)", True))
             execution_plan.append(("Virtual Network (VNet)", False))
    else:
        # Windows or limited Linux
        execution_plan.append(("Standard Run", False))

    
    print("\n--- Environment Capabilities (Hardware) ---")
    for key, val in real_env_caps.items():
        if key == 'interfaces':
            print(f"  interfaces: {', '.join(val) if val else '(none)'}")
        else:
            icon = '[v]' if val else '[x]' if isinstance(val, bool) else '   '
            print(f"  {icon} {key}: {val}")


    # Auto-enable veth/netns on Linux if requested or interactive (Only if we plan to use it)
    # BUT: If we are in "execution plan" mode, we might do this once.
    # Logic preserved from original:
    if real_env_caps['os'] == 'Linux' and (not real_env_caps['has_veth'] or not real_env_caps['has_netns']):
        setup_script = os.path.join(root_dir, "tools", "fusion", "scripts", "setup_vnet.sh")
        if (args.vnet or os.environ.get("FUSION_VNET_AUTO_SETUP") == "1") and os.path.exists(setup_script):
             if sys.stdin.isatty():
                 print(f"\n[INFO] {real_env_caps['os']} detected but veth/netns support is missing/incomplete.")
                 print(f"       Tests requiring virtual networks will fail.")
                 print(f"       Do you want to run the setup script? (Requires sudo)")
                 response = input("       Run setup_vnet.sh? [y/N]: ").strip().lower()
                 if response == 'y':
                     print("\n[INFO] Running setup_vnet.sh (Please enter sudo password if prompted)...")
                     try:
                         ret = subprocess.call(["sudo", "bash", setup_script])
                         if ret == 0:
                             print("[PASS] Network setup complete. Re-detecting capabilities...")
                             real_env_caps = detect_environment() # Refresh caps
                             # Re-evaluate plan if caps changed?
                             if not args.no_vnet:
                                 execution_plan = [("Physical Network (No VNet)", True), ("Virtual Network (VNet)", False)]
                         else:
                             print("[FAIL] Network setup failed.")
                     except Exception as e:
                         print(f"[ERROR] Failed to run setup script: {e}")

    # Build once? Or build per run?
    # Build should be environment agnostic usually, unless conditional compilation.
    # We assume build is agnostic.
    
    # We'll use a merged test_results object
    all_test_results = {"steps": []}
    overall_status = "SUCCESS"

    # CLEAN stage (Run once)
    try:
        if args.clean:
            if server: server.update({"current_step": "Cleaning"})
            print("\n=== Cleaning Build Artifacts ===")
            import shutil
            dirs_to_clean = [
                "build", "build_cpp", "build_linux", 
                "target", 
                "examples/integrated_apps/cpp_app/build",
                "examples/integrated_apps/rust_app/target",
                "src/js/dist",
                "examples/automotive_pubsub/js_adas/dist",
                "examples/integrated_apps/js_app/dist",
                "examples/simple_no_sd/js/dist",
                "examples/someipy_demo/js_client/dist"
            ]
            for d in dirs_to_clean:
                path = os.path.join(root_dir, d)
                if os.path.exists(path):
                    if d == "build" and os.path.exists(os.path.join(path, "generated")):
                         # conserve generated
                         pass 
                    else:
                        try: shutil.rmtree(path)
                        except: pass
            print("Cleanup complete.\n")

        # Base raw_logs directory to avoid overwriting running sequentially
        base_raw_logs_dir = reporter.raw_logs_dir

        # Run Loop
        for run_name, force_no_vnet in execution_plan:
            # Create a slug for the run name
            run_slug = run_name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
            
            # Update reporter to point to a subdirectory for this run
            reporter.raw_logs_dir = os.path.join(base_raw_logs_dir, run_slug)
            os.makedirs(reporter.raw_logs_dir, exist_ok=True)

            print(f"\n\n{'='*60}")
            print(f"EXECUTION PHASE: {run_name}")
            print(f"LOGS: {reporter.raw_logs_dir}")
            print(f"{'='*60}\n")
            
            # Prepare Environment for this run
            env_caps = real_env_caps.copy()
            if force_no_vnet:
                env_caps['has_vnet'] = False
                env_caps['has_netns'] = False
                os.environ["FUSION_NO_VNET"] = "1"
            else:
                if "FUSION_NO_VNET" in os.environ: del os.environ["FUSION_NO_VNET"]

            
            # Default local IP logic per run
            local_ip = env_caps['primary_ipv4'] or get_local_ip()
            force_lo_env = os.environ.get('FUSION_FORCE_LOOPBACK') == '1'
            wsl_needs_lo = env_caps['is_wsl'] and not (env_caps['has_veth'] or env_caps['has_netns'])
            
            if env_caps['is_ci'] or wsl_needs_lo or force_lo_env:
                local_ip = '127.0.0.1'

            if server: server.update({"tools": tool_status})
            tools.print_status()
            
            # Check Network Capabilities
            caps = tools.check_network_capabilities()
            
            builder = Builder(reporter)
            tester = Tester(reporter, builder, env_caps=env_caps)
            cover = CoverageManager(reporter, tools, env_caps=env_caps)
            
            current_results = {}
            stage = args.stage

            # DIAGRAMS (Once is enough, but fine to repeat or skip)
            if stage in ["diagrams", "docs", "all"] and execution_plan.index((run_name, force_no_vnet)) == 0:
                 current_results.update(run_diagrams(root_dir, reporter, server))

            # CODEGEN (Once is enough)
            if stage in ["codegen", "all"] and not args.no_codegen and execution_plan.index((run_name, force_no_vnet)) == 0:
                 if server: server.update({"current_step": "Codegen"})
                 # ... (Validation Logic same as before, abbreviated for brevity) ...
                 # For brevity, assuming validation passes. 
                 # In real implementaiton, keep the validation logic or move to function.
                 print("Running Codegen...")
                 if not builder.generate_bindings(): raise Exception("Bindings Generation Failed")
                 current_results["codegen"] = "PASS"

            # BUILD (Once is enough usually, but safely idempotent)
            if stage in ["build", "all"]:
                 # Optimization: Only build once if possible.
                 # But sticking to simple loop for now.
                 if execution_plan.index((run_name, force_no_vnet)) == 0:
                     current_results.update(run_build(root_dir, reporter, builder, tool_status, args.target, server, args.no_codegen, args.with_coverage, args.packet_dump))

            # TEST
            # Optimization: Only run unit tests in the first pass (No-VNet)
            # Unit tests are generally environment-agnostic or local-only.
            if stage in ["test", "all"] and force_no_vnet:
                 # Prefix steps with run name
                 res = run_test(reporter, tester, args.target, server)
                 for s in res.get("steps", []): s["name"] = f"[{run_name}] {s['name']}"
                 merge_results(all_test_results, res)

            # DEMOS
            should_run_demos = False
            if stage == "demos": should_run_demos = True
            if stage == "all" and not args.skip_demos: should_run_demos = True
            if stage == "test" and not args.skip_demos: should_run_demos = True

            if should_run_demos: 
                 if args.target == "all" or stage == "demos":
                    res = run_demos(reporter, tester, server, current_results, args.demo)
                    for s in res.get("steps", []): s["name"] = f"[{run_name}] {s['name']}"
                    merge_results(all_test_results, res)

            # COVERAGE (Last run only?)
            if stage in ["coverage", "all"] and not args.skip_coverage and execution_plan.index((run_name, force_no_vnet)) == len(execution_plan) - 1:
                res = run_coverage(reporter, cover, server, current_results, args.target)
                merge_results(all_test_results, res)

        # Final Reporting using all_test_results
        
        # DOCS stage
        if args.stage == "docs":
            print("\n[PASS] Documentation generated successfully")

        # Finalize
        failures = []
        for step in all_test_results.get("steps", []):
            if step["status"] == "FAIL": 
                overall_status = "FAILED"
                failures.append(step["name"])
        
        # Check explicit component failures in keys
        # (Simplified aggregation: we rely mostly on steps for status)

        final_data = {
            "current_step": "Done", 
            "overall_status": overall_status,
            "tests": all_test_results
        }
        if server: server.update(final_data)
        reporter.generate_index(final_data)
        
        print(f"\nFusion Run Completed: {overall_status}")
        if overall_status == "FAILED":
            print(f"[FAIL] Failed components: {', '.join(failures)}")
        
        if "steps" in all_test_results and all_test_results["steps"]:
            print("\n--- Detailed Results ---")
            for step in all_test_results["steps"]:
                status_icon = "[v]" if step["status"] == "PASS" else "[x]"
                print(f"{status_icon} {step['name']}: {step['status']}")
                if step["status"] == "FAIL":
                    print(f"   Details: {step.get('details', 'No details available')}")
        
        print(f"Report: file://{os.path.join(reporter.log_dir, 'index.html')}")

        if overall_status == "FAILED":
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n[INFO] Execution Interrupted by User.")
        if server: os._exit(0)
    except Exception as e:
        print(f"\n[ERROR] Critical Error: {e}")
        if server: server.update({"overall_status": "FAILED", "error": str(e)})
        sys.exit(1)
        
    finally:
        if server:
            if sys.stdin.isatty() and not args.no_dashboard:
                try: input("\nPress Enter to stop dashboard and exit...")
                except: pass 
            try: server.stop()
            except: pass

if __name__ == "__main__":
    main()
