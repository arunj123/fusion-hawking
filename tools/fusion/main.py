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


def run_diagrams(root_dir, reporter, server):
    """Stage: Generate PlantUML diagrams"""
    if server: server.update({"current_step": "Generating Diagrams"})
    reporter.generate_index({"current_step": "Generating Diagrams", "overall_status": "RUNNING"})
    diagrams = DiagramManager(root_dir, reporter)
    return diagrams.run()


def run_build(root_dir, reporter, builder, tool_status, target, server, skip_codegen=False):
    """Stage: Build Rust and C++"""
    if server: server.update({"current_step": "Building"})
    reporter.generate_index({"current_step": "Building", "overall_status": "RUNNING", "tools": tool_status})
    print("\n=== Building ===")
    
    if not skip_codegen and target in ["all", "rust", "cpp"]:
        # If running as "build" stage but NOT "all" stage (which handled it), we might need this.
        # But main.py now handles it in "codegen" block if stage is "all".
        # If stage is "build", user might expect it?
        # CI will use --stage build --no-codegen.
        # Local user using --stage build expects codegen.
        if not builder.generate_bindings(): 
            raise Exception("Bindings Generation Failed")
    
    if target in ["all", "rust", "python"]:
        if not builder.build_rust(): 
            raise Exception("Rust Build Failed")
    
    if tool_status.get("cmake") and target in ["all", "cpp"]:
        builder.build_cpp()
    
    # Capture Configuration
    try:
        config_src = os.path.join(os.getcwd(), "build", "generated")
        if os.path.exists(config_src):
            config_dest = os.path.join(reporter.log_dir, "configs")
            import shutil
            shutil.copytree(config_src, config_dest, dirs_exist_ok=True)
            print(f"Captured configurations to {config_dest}")
    except Exception as e:
        print(f"⚠️ Failed to capture configs: {e}")
    
    return {"build": "PASS"}


def run_test(reporter, tester, target, server):
    """Stage: Run unit tests"""
    if server: server.update({"current_step": "Testing"})
    print("\n=== Testing ===")
    
    test_results = {}
    
    if target == "all":
        test_results = tester.run_unit_tests()
    else:
        if target == "rust":
            test_results["rust"] = tester._run_rust_tests()
        elif target == "python":
            test_results.update(tester._run_python_tests())
        elif target == "cpp":
            test_results["cpp"] = tester._run_cpp_tests()
    
    return test_results


def run_demos(reporter, tester, server, test_results, demo_filter):
    """Stage: Run integration demos"""
    if server: server.update({"current_step": "Running Demos"})
    print("\n=== Demos ===")
    demo_results = tester.run_demos(demo_filter)
    test_results.update(demo_results)
    return test_results


def run_coverage(reporter, cover, server, test_results, target):
    """Stage: Generate coverage reports"""
    if server: server.update({"current_step": "Coverage"})
    print("\n=== Coverage ===")
    cov_results = cover.run_coverage(target)
    test_results.update(cov_results)
    return test_results


def main():
    parser = argparse.ArgumentParser(description="Fusion Hawking Automation Tool")
    parser.add_argument("--skip-demos", action="store_true", help="Skip integration demos")
    parser.add_argument("--skip-coverage", action="store_true", help="Skip coverage generation")
    parser.add_argument("--server", action="store_true", default=True, help="Enable dashboard server")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable dashboard server (override)")
    parser.add_argument("--target", type=str, choices=["all", "rust", "python", "cpp"], default="all", help="Target language to test")
    parser.add_argument("--demo", type=str, choices=["all", "simple", "integrated", "pubsub"], default="all", help="Specific demo to run")
    parser.add_argument("--no-codegen", action="store_true", help="Skip codegen (assume artifacts exist)")
    parser.add_argument("--base-port", type=int, default=0, help="Port offset for test isolation")
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
    patch_configs(local_ip, root_dir, args.base_port)
    
    if server: server.update({"tools": tool_status})
    tools.print_status()
    reporter.generate_index({"current_step": "Toolchains Checked", "overall_status": "RUNNING", "tools": tool_status})

    builder = Builder(reporter)
    tester = Tester(reporter, builder)
    cover = CoverageManager(reporter, tools)
    
    test_results = {}

    try:
        # Stage-based execution
        stage = args.stage
        
    # DIAGRAMS stage
        if stage in ["diagrams", "docs", "all"]:
            diagram_results = run_diagrams(root_dir, reporter, server)
            test_results.update(diagram_results)
            
        # CODEGEN Stage (new)
        if stage in ["codegen", "all"] and not args.no_codegen:
            if server: server.update({"current_step": "Codegen"})
            print("\n=== Codegen ===")
            if not builder.generate_bindings():
                raise Exception("Bindings Generation Failed")
            test_results["codegen"] = "PASS"
        
        # BUILD stage
        if stage in ["build", "all"]:
            # Pass no_codegen logic to run_build if needed, or we handled it above.
            # But run_build (line 30) called generate_bindings() unconditionally.
            # We need to modify run_build signature and logic.
            # Let's pass args.no_codegen to run_build
            build_results = run_build(root_dir, reporter, builder, tool_status, args.target, server, args.no_codegen)
            test_results.update(build_results)
        
        # TEST stage
        if stage in ["test", "all"]:
            test_results.update(run_test(reporter, tester, args.target, server))
            if server: server.update({"tests": test_results})
            reporter.generate_index({"current_step": "Tests Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})
        
        # DEMOS (part of test stage if "test" selected, or explicit "demos" stage, or "all")
        # NOTE: If stage is "test" we traditionally ran demos too if not skipped.
        # But for granular CI, we might separate them.
        # Let's say: if stage="demos", run demos.
        # If stage="all", run demos (unless skipped).
        # If stage="test", ideally we only run unit tests now?
        # The legacy behavior was "test" included demos.
        # To avoid breaking local behavior: keep demos in "test" if args.stage == "all"?
        # Actually, let's explicit:
        # If --stage demos is passed, run demos.
        # If --stage all is passed, run demos.
        # If --stage test is passed -> we can choose to NOT run demos if we want strict separation, 
        # but existing users might expect it.
        # Let's keep demos under its own block, but enable it if stage in ["demos", "all"] or (stage=="test" and not args.skip_demos) 
        # Wait, if I split CI, I will use --stage demos.
        # If I use --stage test locally, I might want demos.
        
        should_run_demos = False
        if stage == "demos": should_run_demos = True
        if stage == "all" and not args.skip_demos: should_run_demos = True
        # Maintain legacy behavior: --stage test includes demos unless skipped
        if stage == "test" and not args.skip_demos: should_run_demos = True

        if should_run_demos and args.target == "all" or args.stage == "demos": 
            # Note: args.target == "all" check was preventing single-language tests from running demos?
            # If I run --target rust --stage test, main.py skipped demos before (line 157 in original).
            # I'll respect that logic unless stage is explicitly "demos".
            pass

        # Simplified Logic:
        if (stage in ["demos", "all"] or (stage == "test" and not args.skip_demos)):
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
            print("\n✅ Documentation generated successfully")

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
            print(f"❌ Failed components: {', '.join(failures)}")
            if "steps" in test_results:
                print("\n--- Detailed Results ---")
                for step in test_results["steps"]:
                    status_icon = "✅" if step["status"] == "PASS" else "❌"
                    print(f"{status_icon} {step['name']}: {step['status']}")
                    if step["status"] == "FAIL":
                        print(f"   Details: {step.get('details', 'No details available')}")
        
        print(f"Report: file://{os.path.join(reporter.log_dir, 'index.html')}")

        if overall == "FAILED":
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n🛑 Execution Interrupted by User.")
        if server: 
            os._exit(0)
    except Exception as e:
        print(f"\n❌ Critical Error: {e}")
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
