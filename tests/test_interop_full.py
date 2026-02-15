import subprocess
import os
import time
import sys
import shutil
import json

# Paths
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT)

from tools.fusion.utils import _get_env as get_environment

CPP_EXE = os.path.join(ROOT, "build", "Release", "client_fusion.exe")
# Adjust CPP_EXE path if not found (look in likely places)
if not os.path.exists(CPP_EXE):
     candidates = [
         os.path.join(ROOT, "build", "client_fusion.exe"),
         os.path.join(ROOT, "build", "Debug", "client_fusion.exe"),
         os.path.join(ROOT, "examples", "someipy_demo", "build", "Release", "client_fusion.exe")
     ]
     for c in candidates:
         if os.path.exists(c):
             CPP_EXE = c
             break

JS_DIR = os.path.join(ROOT, "src", "js")
PY_SRC = os.path.join(ROOT, "src", "python")

def generate_config(output_dir):
    """Generate interop configuration."""
    # We write to client_config.json in output_dir (which should be ROOT for clients)
    config_path = os.path.join(output_dir, "client_config.json")
    
    # Detected loopback name
    iface_name = "Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo"
    
    config = {
        "interfaces": {
            "lo": {
                "name": iface_name,
                "sd": {
                    "endpoint": "sd_mcast"
                },
                "endpoints": {
                    "sd_mcast": {
                        "ip": "239.0.0.1",
                        "port": 30491,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "service_ep": {
                        "ip": "127.0.0.1",
                        "port": 40001,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "js_ep": {
                        "ip": "127.0.0.1",
                        "port": 40002,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "cpp_ep": {
                        "ip": "127.0.0.1",
                        "port": 40003,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "rust_ep": {
                        "ip": "127.0.0.1",
                        "port": 40004,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "sd_bind_ep": {
                        "ip": "127.0.0.1",
                        "port": 0,
                        "version": 4,
                        "protocol": "udp"
                    }
                }
            }
        },
        "instances": {
            "PythonService": {
                "unicast_bind": {
                    "lo": "sd_bind_ep"
                },
                "providing": {
                    "MathService": {
                        "service_id": 4660,
                        "instance_id": 1,
                        "major_version": 1,
                        "offer_on": {
                            "lo": "service_ep"
                        }
                    }
                }
            },
            "cpp_client": {
                "required": {
                    "MathService": {
                        "service_id": 4660,
                        "instance_id": 1,
                        "major_version": 1,
                        "find_on": [
                            "lo"
                        ]
                    }
                },
                "unicast_bind": {
                    "lo": "sd_bind_ep"
                }
            },
            "js_client": {
                "required": {
                    "MathService": {
                        "service_id": 4660,
                        "instance_id": 1,
                        "major_version": 1,
                        "find_on": [
                            "lo"
                        ]
                    }
                },
                "unicast_bind": {
                    "lo": "sd_bind_ep"
                }
            },
            "rust_client": {
                "required": {
                    "someipy_svc": {
                        "service_id": 4660,
                        "instance_id": 1,
                        "major_version": 1,
                        "find_on": [
                            "lo"
                        ]
                    }
                },
                "unicast_bind": {
                    "lo": "sd_bind_ep"
                }
            }
        }
    }
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        print(f"Generated config at {config_path}")
        
    return config_path

def cleanup():
    if os.path.exists(os.path.join(ROOT, "client_config.json")): 
        try:
             os.remove(os.path.join(ROOT, "client_config.json"))
        except: pass

def main():
    print("--- Cross-Language Multi-Interface Interop Test ---")
    os.environ["FUSION_PACKET_DUMP"] = "1"
    
    # 1. Generate Config into ROOT (CWD for clients)
    config_path = generate_config(ROOT)
    # Ensure absolute path for Python service
    abs_config_path = os.path.abspath(config_path)
    
    # 2. Start Python Service
    print("[Test] Starting Python Service...")
    # Escape backslashes for windows path in python string
    escaped_src = PY_SRC.replace("\\", "\\\\")
    escaped_config = abs_config_path.replace("\\", "\\\\")
    
    py_svc = subprocess.Popen(
        [sys.executable, "-c", f"""
import sys, os, time
sys.path.append(r'{escaped_src}')
from fusion_hawking import SomeIpRuntime, RequestHandler, ConsoleLogger
class Handler(RequestHandler):
    def get_service_id(self): return 0x1234
    def handle(self, mi, p):
        print(f"[Python Service] Handling Request: {{p.decode()}}")
        return b"Response from Python!"
rt = SomeIpRuntime(r'{escaped_config}', 'PythonService')
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
    # C++ Client likely expects client_config.json in CWD
    if os.path.exists(CPP_EXE):
        cpp_res = subprocess.run([CPP_EXE], capture_output=True, text=True, cwd=ROOT)
        print("C++ STDOUT:\n", cpp_res.stdout)
        print("C++ STDERR:\n", cpp_res.stderr)
    else:
        print(f"C++ Executable not found at {CPP_EXE}, skipping.")
        cpp_res = None
    
    # 4. Start JS Client
    print("[Test] Starting JS Client...")
    # Pass config path as arg
    js_res = subprocess.run(["node", "tests/interop_client.mjs", abs_config_path], capture_output=True, text=True, cwd=ROOT)
    print("JS STDOUT:\n", js_res.stdout)
    print("JS STDERR:\n", js_res.stderr)
    
    # 5. Start Rust Client
    print("[Test] Starting Rust Client...")
    # rust client likely expects client_config.json in CWD
    rust_bin = "target/debug/someipy_client"
    if os.name == 'nt': rust_bin += ".exe"
    rust_bin_path = os.path.join(ROOT, rust_bin)
    
    if os.path.exists(rust_bin_path):
        rust_res = subprocess.run([rust_bin_path], capture_output=True, text=True, cwd=ROOT)
        with open("rust_stdout.log", "w") as f: f.write(rust_res.stdout)
        with open("rust_stderr.log", "w") as f: f.write(rust_res.stderr)
        print("Writing Rust logs to rust_stdout.log and rust_stderr.log")
    else:
        print(f"Rust binary not found at {rust_bin_path}, skipping.")
        rust_res = None
    
    # Cleanup Python service
    py_svc.terminate()
    cleanup()
    
    # Verify results
    cpp_ok = cpp_res and "Got Response: 'Response from Python!'" in cpp_res.stdout
    js_ok = "Got Response: Response from Python!" in js_res.stdout
    rust_ok = rust_res and "Got Response: 'Response from Python!'" in rust_res.stdout
    
    if (cpp_res is None or cpp_ok) and js_ok and (rust_res is None or rust_ok):
        print("--- INTEROP SUCCESS ---")
        if cpp_res is None: print("(C++ Skipped)")
        if rust_res is None: print("(Rust Skipped)")
        sys.exit(0)
    else:
        print("--- INTEROP FAILURE ---")
        if cpp_res and not cpp_ok: print("C++ Client Failed")
        if not js_ok: print("JS Client Failed")
        if rust_res and not rust_ok: print("Rust Client Failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
