import subprocess
import os
import time
import sys
import shutil

# Paths
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CPP_EXE = os.path.join(ROOT, "build", "Release", "client_fusion.exe")
JS_DIR = os.path.join(ROOT, "src", "js")
PY_SRC = os.path.join(ROOT, "src", "python")
CONFIG = os.path.join(ROOT, "tests", "interop_multi_config.json")

def cleanup():
    if os.path.exists("client_config.json"): os.remove("client_config.json")

def main():
    print("--- Cross-Language Multi-Interface Interop Test ---")
    os.environ["FUSION_PACKET_DUMP"] = "1"
    
    # 1. Prepare C++ config (it expects client_config.json in CWD)
    shutil.copy(CONFIG, "client_config.json")
    
    # 2. Start Python Service
    print("[Test] Starting Python Service...")
    py_svc = subprocess.Popen(
        [sys.executable, "-c", f"""
import sys, os, time
sys.path.append(r'{PY_SRC}')
from fusion_hawking import SomeIpRuntime, RequestHandler, ConsoleLogger
class Handler(RequestHandler):
    def get_service_id(self): return 0x1234
    def handle(self, mi, p):
        print(f"[Python Service] Handling Request: {{p.decode()}}")
        return b"Response from Python!"
rt = SomeIpRuntime(r'{CONFIG}', 'PythonService')
rt.offer_service('MathService', Handler())
rt.start()
try:
    while True: time.sleep(1)
except KeyboardInterrupt: rt.stop()
        """],
        text=True
    )
    
    time.sleep(3) # Wait for SD to start offering
    
    # 3. Start C++ Client
    print("[Test] Starting C++ Client...")
    cpp_res = subprocess.run([CPP_EXE], capture_output=True, text=True)
    print("C++ STDOUT:\n", cpp_res.stdout)
    print("C++ STDERR:\n", cpp_res.stderr)
    
    # 4. Start JS Client
    print("[Test] Starting JS Client...")
    js_res = subprocess.run(["node", "tests/interop_client.mjs"], capture_output=True, text=True, cwd=ROOT)
    print("JS STDOUT:\n", js_res.stdout)
    print("JS STDERR:\n", js_res.stderr)
    
    # 5. Start Rust Client
    print("[Test] Starting Rust Client...")
    # rust client expects client_config.json
    rust_res = subprocess.run(["target/debug/someipy_client.exe"], capture_output=True, text=True, cwd=ROOT)
    with open("rust_stdout.log", "w") as f: f.write(rust_res.stdout)
    with open("rust_stderr.log", "w") as f: f.write(rust_res.stderr)
    print("Writing Rust logs to rust_stdout.log and rust_stderr.log")
    
    # Cleanup Python service
    py_svc.terminate()
    cleanup()
    
    # Verify results
    cpp_ok = "Got Response: 'Response from Python!'" in cpp_res.stdout
    js_ok = "Got Response: Response from Python!" in js_res.stdout
    rust_ok = "Got Response: 'Response from Python!'" in rust_res.stdout
    
    if cpp_ok and js_ok and rust_ok:
        print("--- INTEROP SUCCESS ---")
        sys.exit(0)
    else:
        print("--- INTEROP FAILURE ---")
        if not cpp_ok: print("C++ Client Failed")
        if not js_ok: print("JS Client Failed")
        if not rust_ok: print("Rust Client Failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
