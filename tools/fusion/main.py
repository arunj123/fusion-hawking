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
from tools.fusion.utils import get_local_ip, patch_configs
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


def run_build(root_dir, reporter, builder, tool_status, target, server, skip_codegen=False, with_coverage=False):
    """Stage: Build Rust and C++"""
    if server: server.update({"current_step": "Building"})
    reporter.generate_index({"current_step": "Building", "overall_status": "RUNNING", "tools": tool_status})
    print("\n=== Building ===")
    
    if not skip_codegen and target in ["all", "rust", "cpp"]:
        # If running as "build" stage but NOT "all" stage (which handled it), we might need this.
        if not builder.generate_bindings(): 
            raise Exception("Bindings Generation Failed")
    
    if target in ["all", "rust", "python"]:
        if not builder.build_rust(): 
            raise Exception("Rust Build Failed")
    
    if tool_status.get("cmake") and target in ["all", "cpp", "python"]:
        if not builder.build_cpp(with_coverage):
            raise Exception("C++ Build Failed")

    if target in ["all", "js"]:
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
    
    # Patch configs with local IP and Port Offset
    local_ip = get_local_ip()
    
    # Force loopback in GitHub Actions (internal networking is often unreliable for UDP SD)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("[INFO] CI detected: forcing loopback (127.0.0.1) for stability")
        local_ip = "127.0.0.1"
        
    patch_configs(local_ip, root_dir, args.base_port)
    
    if server: server.update({"tools": tool_status})
    tools.print_status()
    reporter.generate_index({"current_step": "Toolchains Checked", "overall_status": "RUNNING", "tools": tool_status})

    builder = Builder(reporter)
    tester = Tester(reporter, builder)
    cover = CoverageManager(reporter, tools)
    
    test_results = {}

    try:
        # CLEAN stage
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
                    # Special case: don't delete build/generated if we are cleaning 'build'
                    # as it might have been provided by a previous CI stage
                    if d == "build" and os.path.exists(os.path.join(path, "generated")):
                        print(f"Cleaning {d} but preserving {d}/generated...")
                        for item in os.listdir(path):
                            if item == "generated":
                                continue
                            item_path = os.path.join(path, item)
                            try:
                                if os.path.isdir(item_path):
                                    shutil.rmtree(item_path)
                                else:
                                    os.remove(item_path)
                            except Exception as e:
                                print(f"[WARN] Failed to remove {item_path}: {e}")
                    else:
                        print(f"Removing {d}...")
                        try:
                            shutil.rmtree(path)
                        except Exception as e:
                            print(f"[WARN] Failed to remove {d}: {e}")
            print("Cleanup complete.\n")

        # Stage-based execution
        stage = args.stage
        
    # DIAGRAMS stage
        if stage in ["diagrams", "docs", "all"]:
            diagram_results = run_diagrams(root_dir, reporter, server)
            test_results.update(diagram_results)
            
        # CODEGEN Stage (new)
        if stage in ["codegen", "all"] and not args.no_codegen:
            if server: server.update({"current_step": "Codegen"})
            print("\n=== Codegen & Validation ===")
            
            # Run Config Validation
            from tools.fusion.config_validator import validate_config
            import json
            
            # Find all config.json files
            config_errors = []
            for root, _, files in os.walk(root_dir):
                if "config.json" in files and "build" not in root:
                    config_path = os.path.join(root, "config.json")
                    try:
                        with open(config_path, "r") as f:
                            data = json.load(f)
                        errs = validate_config(data)
                        if errs:
                            print(f"[FAIL] Config Validation Failed for {config_path}")
                            for e in errs:
                                print(f" - {e}")
                                config_errors.append(f"{config_path}: {e}")
                        else:
                            print(f"[PASS] Validated {config_path}")
                    except Exception as e:
                        print(f"[WARN] Could not validate {config_path}: {e}")
            
            if config_errors:
                 raise Exception("Configuration Validation Failed (see logs)")
            
            if not builder.generate_bindings():
                raise Exception("Bindings Generation Failed")
            test_results["codegen"] = "PASS"
        
        # BUILD stage
        if stage in ["build", "all"]:
            build_results = run_build(root_dir, reporter, builder, tool_status, args.target, server, args.no_codegen, args.with_coverage)
            test_results.update(build_results)
        
        # TEST stage
        if stage in ["test", "all"]:
            test_results.update(run_test(reporter, tester, args.target, server))
            if server: server.update({"tests": test_results})
            reporter.generate_index({"current_step": "Tests Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})
        
        # DEMOS
        should_run_demos = False
        if stage == "demos": should_run_demos = True
        if stage == "all" and not args.skip_demos: should_run_demos = True
        # Maintain legacy behavior: --stage test includes demos unless skipped
        if stage == "test" and not args.skip_demos: should_run_demos = True

        if should_run_demos: 
             # Only run if target is all OR stage is explicitly demos
             if args.target == "all" or stage == "demos":
                test_results = run_demos(reporter, tester, server, test_results, args.demo)
                if server: server.update({"tests": test_results})
                reporter.generate_index({"current_step": "Demos Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})
        
        # COVERAGE stage
        if stage in ["coverage", "all"] and not args.skip_coverage:
            test_results = run_coverage(reporter, cover, server, test_results, args.target)
            if server: server.update({"tests": test_results})
            reporter.generate_index({"current_step": "Coverage Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})

        # DOCS stage (diagrams + report generation)
        if stage == "docs":
            # Diagrams already run above
            reporter.generate_index({"current_step": "Docs Generated", "overall_status": "SUCCESS", "tools": tool_status, "tests": test_results})
            print("\n[PASS] Documentation generated successfully")

        # Finalize
        overall = "SUCCESS"
        failures = []
        for k, v in test_results.items():
            if k == "steps": continue
            if v == "FAIL" or v is False: 
                overall = "FAILED"
                failures.append(k)
        
        final_data = {
            "current_step": "Done", 
            "overall_status": overall,
            "tests": test_results
        }
        if server: server.update(final_data)
        reporter.generate_index(final_data)
        
        print(f"\nFusion Run Completed: {overall}")
        if overall == "FAILED":
            print(f"[FAIL] Failed components: {', '.join(failures)}")
        
        if "steps" in test_results and test_results["steps"]:
            print("\n--- Detailed Results ---")
            for step in test_results["steps"]:
                status_icon = "[v]" if step["status"] == "PASS" else "[x]"
                print(f"{status_icon} {step['name']}: {step['status']}")
                if step["status"] == "FAIL":
                    print(f"   Details: {step.get('details', 'No details available')}")
        
        print(f"Report: file://{os.path.join(reporter.log_dir, 'index.html')}")

        if overall == "FAILED":
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n[INFO] Execution Interrupted by User.")
        if server: 
            os._exit(0)
    except Exception as e:
        print(f"\n[ERROR] Critical Error: {e}")
        if server: server.update({"overall_status": "FAILED", "error": str(e)})
        sys.exit(1)
        
    finally:
        if server:
            if sys.stdin.isatty() and not args.no_dashboard:
                try:
                    input("\nPress Enter to stop dashboard and exit...")
                except:
                    pass 
            
            try:
                server.stop()
            except:
                pass

if __name__ == "__main__":
    main()
