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

def main():
    parser = argparse.ArgumentParser(description="Fusion Hawking Automation Tool")
    parser.add_argument("--skip-demos", action="store_true", help="Skip integration demos")
    parser.add_argument("--skip-coverage", action="store_true", help="Skip coverage generation")
    parser.add_argument("--server", action="store_true", default=True, help="Enable dashboard server")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable dashboard server (override)")
    parser.add_argument("--target", type=str, choices=["all", "rust", "python", "cpp"], default="all", help="Target language to test")
    args = parser.parse_args()

    # Get Root Directory (assuming running from root or finding it)
    root_dir = os.path.abspath(os.getcwd())
    
    # Initialize Components
    # Initialize Reporter FIRST to ensure index.html and directories exist
    reporter = Reporter(root_dir)

    # Server logic: Enable if --server is True AND --no-dashboard is False
    enable_server = args.server and not args.no_dashboard
    
    # IMPORTANT: If this is a child process spawned by the dashboard, we DO NOT want to bind port 8000 again.
    server = ProgressServer(report_dir=os.path.join(root_dir, "logs")) if enable_server else None
    
    if server: 
        server.start()
        server.update({"current_step": "Initializing", "overall_status": "RUNNING"})
    
    tools = ToolchainManager()
    tool_status = tools.check_all()
    if server: server.update({"tools": tool_status})
    tools.print_status()
    reporter.generate_index({"current_step": "Toolchains Checked", "overall_status": "RUNNING", "tools": tool_status})

    builder = Builder(reporter)
    tester = Tester(reporter, builder)
    cover = CoverageManager(reporter, tools)

    try:
        # 1. Build (Always build required components, or filter?)
        # For simplicity, we build all if target is all or specific. 
        # Incremental builds make this cheap.
        if server: server.update({"current_step": "Building"})
        reporter.generate_index({"current_step": "Building", "overall_status": "RUNNING", "tools": tool_status})
        print("\n=== Building ===")
        
        if not builder.generate_bindings(): raise Exception("Bindings Generation Failed")
        
        # Build Rust if target is all or rust or dependent? (Python depends on specific impl? No, bindings)
        if args.target in ["all", "rust", "python"]: # Python often wraps Rust or C++? Assume independent for now or build all.
             if not builder.build_rust(): raise Exception("Rust Build Failed")
        
        if tool_status["cmake"] and args.target in ["all", "cpp"]:
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

        # 2. Tests
        if server: server.update({"current_step": "Testing"})
        print("\n=== Testing ===")
        
        test_results = {}
        
        # Filter tests based on target
        if args.target == "all":
            test_results = tester.run_unit_tests()
        else:
            # Run specific test
            if args.target == "rust":
                test_results["rust"] = tester._run_rust_tests()
            elif args.target == "python":
                test_results.update(tester._run_python_tests())
            elif args.target == "cpp":
                test_results["cpp"] = tester._run_cpp_tests()
                
        if server: server.update({"tests": test_results})
        reporter.generate_index({"current_step": "Tests Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})
        
        # 3. Demos
        if not args.skip_demos and args.target == "all":
            if server: server.update({"current_step": "Running Demos"})
            print("\n=== Demos ===")
            demo_results = tester.run_demos()
            test_results.update(demo_results)
            if server: server.update({"tests": test_results})
            reporter.generate_index({"current_step": "Demos Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})

        # 4. Coverage (Only for all or specific?)
        if not args.skip_coverage and args.target == "all":
            if server: server.update({"current_step": "Coverage"})
            print("\n=== Coverage ===")
            cov_results = cover.run_coverage()
            test_results.update(cov_results)
            if server: server.update({"tests": test_results})
            reporter.generate_index({"current_step": "Coverage Completed", "overall_status": "RUNNING", "tools": tool_status, "tests": test_results})
        elif not args.skip_coverage and args.target != "all":
            # Run specific coverage?
            pass # Coverage usually runs all suite. Keep it simple for now.

        # Finalize
        overall = "SUCCESS"
        for k, v in test_results.items():
            if v == "FAIL" or v is False: 
                overall = "FAILED"
                break
        
        final_data = {
            "current_step": "Done", 
            "overall_status": overall,
            "tests": test_results
        }
        if server: server.update(final_data)
        reporter.generate_index(final_data)
        
        print(f"\nExample Run Completed: {overall}")
        print(f"Report: file://{os.path.join(reporter.log_dir, 'index.html')}")

        if overall == "FAILED":
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n🛑 Execution Interrupted by User.")
        if server: 
            # Force immediate exit, skipping cleanup that might hang
            # Daemon threads (server) will be killed automatically
            os._exit(0)
    except Exception as e:
        print(f"\n❌ Critical Error: {e}")
        if server: server.update({"overall_status": "FAILED", "error": str(e)})
        sys.exit(1)
        
    finally:
        if server:
            # Only block if we truly own the dashboard and are interactive
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
