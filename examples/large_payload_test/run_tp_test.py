import argparse
import sys
import os
import time
import logging

# Ensure we can import tools from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"DEBUG: PROJECT_ROOT={PROJECT_ROOT}")
print(f"DEBUG: sys.path[0]={sys.path[0]}")

from tools.fusion.environment import NetworkEnvironment
from tools.fusion.config_gen import SmartConfigFactory
from tools.fusion.integration import IntegrationTestContext
from tools.fusion.utils import find_binary, to_wsl

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_tp_test")

def get_binary(lang, name):
    if lang == "rust":
        # Search target/debug, target/release
        candidates = [
            os.path.join(PROJECT_ROOT, "target", "debug"),
            os.path.join(PROJECT_ROOT, "target", "release"),
        ]
        return find_binary(name, search_dirs=candidates, root=PROJECT_ROOT)
    elif lang == "cpp":
        # Search build/Release, build_linux
        candidates = [
            os.path.join(PROJECT_ROOT, "build", "Release"),
            os.path.join(PROJECT_ROOT, "build"),
            os.path.join(PROJECT_ROOT, "build_linux", "examples", "large_payload_test"),
        ]
        return find_binary(name, search_dirs=candidates, root=PROJECT_ROOT)
    return None

def main():
    parser = argparse.ArgumentParser(description="Cross-Language Large Payload Test Runner")
    parser.add_argument("--server", default="python", choices=["python", "rust", "cpp"])
    parser.add_argument("--client", default="python", choices=["python", "rust", "cpp", "js"])
    args = parser.parse_args()

    # 1. Detect Environment
    env = NetworkEnvironment()
    env.detect()
    
    # 2. Generate Configuration
    factory = SmartConfigFactory(env)
    
    # Use build directory for configs to keep source clean
    config_out_dir = os.path.join(PROJECT_ROOT, "build", "large_payload_test_config")
    os.makedirs(config_out_dir, exist_ok=True)
    
    logger.info(f"Generating configs in {config_out_dir} (VNet={env.has_vnet})")
    config_ret = factory.generate_large_payload_test(config_out_dir)
    
    # Resolve Config Paths and Namespaces
    if os.path.isdir(config_ret) and "config_server.json" in os.listdir(config_ret):
        # Distributed VNet
        server_config = os.path.join(config_ret, "config_server.json")
        client_config = os.path.join(config_ret, "config_client.json")
        ns_server = "ns_ecu1" if env.has_vnet else None
        ns_client = "ns_ecu2" if env.has_vnet else None
    else:
        # Single Config
        server_config = config_ret
        client_config = config_ret
        ns_server = None
        ns_client = None

    # Convert to WSL paths if needed (for runners usage)
    server_config_wsl = to_wsl(server_config)
    client_config_wsl = to_wsl(client_config)

    # 3. Execution Context
    with IntegrationTestContext("large_payload_test") as ctx:
        logger.info(f"Starting Test: Server={args.server}({ns_server}) Client={args.client}({ns_client})")
        
        # --- Start Server ---
        server_cmd = []
        server_cwd = None
        if args.server == "python":
            server_script = os.path.join(os.path.dirname(__file__), "server.py")
            server_cmd = [sys.executable, "-u", server_script, "--config", server_config_wsl]
            # Ensure PYTHONPATH includes src/python
            env_vars = os.environ.copy()
            env_vars["PYTHONPATH"] = os.path.join(PROJECT_ROOT, "src", "python")
            ctx.add_runner("server", server_cmd, env=env_vars, ns=ns_server).start()
            
        elif args.server == "rust":
            bin_path = get_binary("rust", "large_payload_server")
            if not bin_path:
                logger.error("Rust server binary not found!")
                sys.exit(1)
            # Rust server takes config as first arg
            server_cmd = [to_wsl(bin_path), server_config_wsl]
            ctx.add_runner("server", server_cmd, ns=ns_server).start()
            
        elif args.server == "cpp":
            bin_path = get_binary("cpp", "large_payload_server")
            if not bin_path:
                logger.error("C++ server binary not found!")
                sys.exit(1)
            server_cmd = [to_wsl(bin_path), server_config_wsl]
            ctx.add_runner("server", server_cmd, ns=ns_server).start()

        # Allow server to initialize
        time.sleep(2)
        
        # --- Start Client ---
        client_runner = None
        if args.client == "python":
            client_script = os.path.join(os.path.dirname(__file__), "client.py")
            client_cmd = [sys.executable, "-u", client_script, client_config_wsl]
            env_vars = os.environ.copy()
            env_vars["PYTHONPATH"] = os.path.join(PROJECT_ROOT, "src", "python")
            client_runner = ctx.add_runner("client", client_cmd, env=env_vars, ns=ns_client)
            client_runner.start()
            
        elif args.client == "rust":
            bin_path = get_binary("rust", "large_payload_client")
            if not bin_path:
                logger.error("Rust client binary not found!")
                sys.exit(1)
            client_cmd = [to_wsl(bin_path), client_config_wsl]
            client_runner = ctx.add_runner("client", client_cmd, ns=ns_client)
            client_runner.start()
            
        elif args.client == "cpp":
            bin_path = get_binary("cpp", "large_payload_client")
            if not bin_path:
                logger.error("C++ client binary not found!")
                sys.exit(1)
            client_cmd = [to_wsl(bin_path), client_config_wsl]
            client_runner = ctx.add_runner("client", client_cmd, ns=ns_client)
            client_runner.start()
            
        elif args.client == "js":
            js_dir = os.path.join(os.path.dirname(__file__), "js")
            client_script = os.path.join(js_dir, "client.js")
            # node client.js <config_path>
            client_cmd = ["node", to_wsl(client_script), client_config_wsl]
            # Ensure NODE_PATH if needed
            env_vars = os.environ.copy()
            # If we need to set NODE_PATH for modules, assume they are in src/js/node_modules or similar
            # For now, rely on standard resolution
            client_runner = ctx.add_runner("client", client_cmd, cwd=js_dir, env=env_vars, ns=ns_client)
            client_runner.start()

        # --- Verification ---
        success = False
        logger.info("Waiting for client verification...")
        
        # Check for generic success messages or specific ones
        # Rust client prints "SUCCESS: Content Verified"
        # Python client prints "SUCCESS: Content Verified"
        # C++ client should print similar
        # JS client prints "SUCCESS: Content Verified" (implied)
        
        if args.client in ["rust", "python"]:
            # These clients print "SUCCESS: ECHO..."
            if client_runner.wait_for_output("SUCCESS: ECHO Content Verified", timeout=30):
                success = True
            else:
                logger.error("Echo verification failed")
        else:
            # JS/C++ might verify differently
            if client_runner.wait_for_output("SUCCESS: Content Verified", timeout=30):
                 success = True
        
        if success:
            logger.info("TEST PASSED")
            sys.exit(0)
        else:
            logger.error("TEST FAILED")
            # Dump logs
            print("--- Client Output ---")
            if client_runner and client_runner.log_path and os.path.exists(client_runner.log_path):
                with open(client_runner.log_path, 'r') as f: print(f.read())
            
            print("--- Server Output ---")
            server_runner = ctx.get_runner("server")
            if server_runner and server_runner.log_path and os.path.exists(server_runner.log_path):
                with open(server_runner.log_path, 'r') as f: print(f.read())
            sys.exit(1)

if __name__ == "__main__":
    main()
