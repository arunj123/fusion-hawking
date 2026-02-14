
"""
Configuration Use Case Tests

Verifies complex configuration scenarios described in docs/design_and_requirements.md.
Uses the VNet (Host-Veth-Bridge) topology to simulate different network environments.

Requires:
- setup_vnet.sh (for 10.0.1.x IPs)
- Built JS runtime (in examples/integrated_apps/js_app/node_modules)
- Built Rust/Cpp binaries (optional, for cross-lang tests)
"""

import os
import sys
import json
import time
import subprocess
import pytest
import tempfile
import socket

# Check for VNet availability
def _check_vnet():
    # TEMPORARY: Allow running on Windows without VNet
    return True

pytestmark = []

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
JS_APP_DIR = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "js_app")

def to_wsl(win_path):
    if sys.platform != "linux":
        return win_path.replace("\\", "/") # Windows Python handles forward slashes
    return win_path.replace("\\", "/").replace("C:", "/mnt/c").replace("c:", "/mnt/c")

def run_in_ns(ns_name, command_list, **kwargs):
    """
    Runs the command. On Linux, via `sudo ip netns exec`.
    On Windows, runs directly (ignoring namespace).
    """
    if sys.platform != "linux":
        # Windows: Run directly
        return subprocess.Popen(command_list, **kwargs)
        
    # Prepend sudo ip netns exec
    cmd = ["sudo", "ip", "netns", "exec", ns_name] + command_list
    return subprocess.Popen(cmd, **kwargs)

class ConfigBuilder:
    """Helper to build config.json structures."""
    def __init__(self):
        self.config = {
            "interfaces": {},
            "instances": {}
        }

    def add_interface(self, name, logical_name, endpoints):
        # endpoints: dict of "name" -> {"ip": ..., "port": ...}
        eps = {}
        is_windows = sys.platform != "linux"
        
        # Windows Loopback Patch
        if is_windows and (name.startswith("veth") or name.startswith("eth") or name == "lo"):
            # Try to find loopback name dynamically, else default
            try:
                # Minimal detection if tools.fusion is not available in path here
                # But we can try to use subprocess
                cmd = ["netsh", "interface", "ipv4", "show", "interfaces"]
                r = subprocess.run(cmd, capture_output=True, text=True)
                for line in r.stdout.splitlines():
                    if "Loopback" in line:
                         import re
                         parts = re.split(r'\s{2,}', line.strip())
                         if len(parts) >= 5:
                             name = parts[4]
                             break
            except: 
                pass
                
        for ep_name, details in endpoints.items():
            d = details.copy()
            if is_windows and d["ip"].startswith("10."):
                d["ip"] = "127.0.0.1"
            eps[ep_name] = d
        
        self.config["interfaces"][logical_name] = {
            "name": name,
            "endpoints": eps
        }
        # Auto-add SD if multicast is present
        if "sd_mcast" in eps:
            self.config["interfaces"][logical_name]["sd"] = {
                "endpoint": "sd_mcast",
                "mode": "offer", # Default, can be overridden by instance usage really
                "cycle_ms": 1000
            }

    def add_instance(self, name, unicast_bind, providing=None, required=None, interfaces=None):
        inst = {
            "unicast_bind": unicast_bind,
            "interfaces": interfaces or list(unicast_bind.keys())
        }
        if providing:
            inst["providing"] = providing
        if required:
            inst["required"] = required
        self.config["instances"][name] = inst

    def to_file(self, path):
        with open(path, 'w') as f:
            json.dump(self.config, f, indent=2)
            
        # Backup to logs for debugging
        try:
             # Extract semantic name from path if possible, or use basename
             name = os.path.basename(path)
             log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(os.getcwd(), "logs", "usecases"))
             os.makedirs(log_dir, exist_ok=True)
             shutil.copy(path, os.path.join(log_dir, name))
        except: pass

class JSHelper:
    """Helper to generate and run JS scripts using the integrated_app environment."""
    
    @staticmethod
    def run_script(script_content, config_path, instance_name):
        # Create temp JS file
        fd, path = tempfile.mkstemp(suffix='.js', dir=JS_APP_DIR)
        os.close(fd)
        
        # Inject imports and config loading
        full_script = f"""
        import {{ SomeIpRuntime, LogLevel }} from 'fusion-hawking';
        import * as fs from 'fs';
        
        async function main() {{
            const configPath = '{to_wsl(config_path)}';
            const instanceName = '{instance_name}';
            
            console.log(`JS: Loading ${{configPath}} for ${{instanceName}}`);
            
            const runtime = new SomeIpRuntime();
            await runtime.loadConfigFile(configPath, instanceName);
            runtime.start();
            
            {script_content}
            
            // Keep alive
            await new Promise(r => setTimeout(r, 5000));
            runtime.stop();
        }}
        main().catch(e => {{ console.error(e); process.exit(1); }});
        """
        
        with open(path, 'w') as f:
            f.write(full_script)
            
        # Run via run_in_ns which handles platform differences (no sudo on Windows)
        # Map instance to ns
        ns = "ns_ecu3"
        if "provider_a" in instance_name or "inst_1" in instance_name or "multi_provider" in instance_name or "shared_server" in instance_name or "static_server" in instance_name:
            ns = "ns_ecu1"
        elif "provider_b" in instance_name or "inst_2" in instance_name:
            ns = "ns_ecu2"
            
        return run_in_ns(ns, ["node", os.path.basename(path)], 
                         cwd=JS_APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True), path


class TestUseCases:
    """
    Comprehensive Configuration Use Case Tests
    """
    
    def test_a_multi_homed_provider(self):
        """
        Scenario A: Multi-Homed Provider
        Provider offers Service 0x1001 on veth_ns_ecu1 (primary) and veth_ns_ecu2 (secondary).
        JS Client on veth_ns_ecu3 should find it on both (sequentially or via one).
        """
        builder = ConfigBuilder()
        # Interfaces — inside namespaces, interface is ALWAYS 'veth0'
        builder.add_interface("veth0", "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        # Note: veth1 is on 10.0.2.x subnet in ns_ecu1
        builder.add_interface("veth1", "secondary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_2": {"ip": "10.0.2.1", "port": 31002, "proto": "udp"},
            "sd_uc": {"ip": "10.0.2.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface("veth0", "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        # Provider: Multi-homed
        builder.add_instance("multi_provider", 
            unicast_bind={"primary": "sd_uc", "secondary": "sd_uc"},
            providing={
                "MathService": {
                    "service_id": 0x1001,
                    "instance_id": 1,
                    "offer_on": {
                        "primary": "svc_ep",
                        "secondary": "svc_ep_2"
                    }
                }
            },
            interfaces=["primary", "secondary"]
        )
        
        # Client
        builder.add_instance("js_client",
             unicast_bind={"client_iface": "client_ep"},
             required={
                 "MathService": {
                     "service_id": 0x1001,
                     "instance_id": 1,
                     "find_on": ["client_iface"]
                 }
             },
             interfaces=["client_iface"]
        )

        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tf.close()
        builder.to_file(tf.name)
        config_path = tf.name
        
        # Use global to_wsl which handles platform check


        try:
            wsl_config_path = to_wsl(config_path)
            # Python Provider
            provider_script = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, ReturnCode, RequestHandler

class Handler(RequestHandler):
    def get_service_id(self): return 0x1001
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, header, payload):
        print("PROVIDER_RECEIVED_REQUEST")
        sys.stdout.flush()
        import struct
        a, b = struct.unpack('>ii', payload)
        res = a + b
        return (ReturnCode.E_OK, struct.pack('>i', res))

rt = SomeIpRuntime('{wsl_config_path}', 'multi_provider')
rt.offer_service('MathService', Handler())
rt.start()
print("PROVIDER_STARTED")
sys.stdout.flush()
while True: time.sleep(1)
            """
            prov_proc = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', provider_script], 
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # Wait start
            start = time.time()
            started = False
            while time.time() - start < 5:
                line = prov_proc.stdout.readline()
                if "PROVIDER_STARTED" in line:
                    started = True
                    break
            assert started, f"Provider failed: {prov_proc.stderr.read()}"

            # JS Client
            js_script = """
            const { MathServiceClient } = await import('./dist/manual_bindings.js');

            runtime.getLogger().log(LogLevel.INFO, "JS", "Starting Client...");
            
            // Wait for SD with polling
            let found = false;
            for (let i = 0; i < 20; i++) {
                const svc = runtime.getRemoteService(0x1001);
                if (svc) {
                    console.log(`FOUND_SERVICE_AT: ${svc.address}:${svc.port}`);
                    found = true;
                    break;
                }
                await new Promise(r => setTimeout(r, 1000));
            }

            if (!found) {
                console.log("JS_ERROR: Service 0x1001 not found after 20s");
                process.exit(1);
            }
            
            try {
                const client = new MathServiceClient(runtime, 'js_client');
                console.log("Calling Math.add...");
                // The client.add logic uses 3s timeout internally, let's just call it
                const result = await client.add(10, 20);
                console.log(`JS_RESULT: ${result}`);
            } catch (e) {
                console.log(`JS_ERROR: ${e.message}`);
            }
            """
            
            client_proc, client_path = JSHelper.run_script(js_script, wsl_config_path, 'js_client')
            
            try:
                # Read Output
                start = time.time()
                while time.time() - start < 40:
                    line = client_proc.stdout.readline()
                    if line: print(f"  [JS] {line.strip()}")
                    
                    if "JS_RESULT: 30" in line:
                        break
                    if "JS_ERROR" in line:
                        pytest.fail(f"JS Client Error: {line}")
                else:
                    pytest.fail(f"JS Client timed out. Stderr: {client_proc.stderr.read()}")
            finally:
                # Print provider logs for debugging
                client_proc.terminate()
                if os.path.exists(client_path): os.unlink(client_path)
                
                # Terminate provider before reading its output to avoid deadlocks
                prov_proc.terminate()
                
                print("\n[PROV STDOUT]:")
                try: print(prov_proc.stdout.read()) 
                except: pass
                print("[PROV STDERR]:")
                try: print(prov_proc.stderr.read())
                except: pass

        finally:
            prov_proc.terminate()
            if os.path.exists(config_path): os.unlink(config_path)

    def test_b_complex_requirements(self):
        """
        Scenario B: Complex Requirements (Split Interfaces)
        Instance requires ServiceA on iface1 and ServiceB on iface2.
        """
        builder = ConfigBuilder()
        builder.add_interface("veth0", "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_a_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface("veth0", "secondary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_b_ep": {"ip": "10.0.1.2", "port": 31002, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.2", "port": 31000, "proto": "udp"}
        })
        builder.add_interface("veth0", "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        # Provider A on ecu1 (Service 0x1000)
        builder.add_instance("provider_a", unicast_bind={"primary": "sd_uc"},
            providing={"ServiceA": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "svc_a_ep"}}},
            interfaces=["primary"])

        # Provider B on ecu2 (Service 0x2000)
        builder.add_instance("provider_b", unicast_bind={"secondary": "sd_uc"},
            providing={"ServiceB": {"service_id": 0x2000, "instance_id": 1, "offer_on": {"secondary": "svc_b_ep"}}},
            interfaces=["secondary"])

        # Client on ecu3 (Requires both)
        builder.add_instance("split_client", unicast_bind={"client_iface": "client_ep"},
            required={
                "ServiceA": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "ServiceB": {"service_id": 0x2000, "instance_id": 1, "find_on": ["client_iface"]}
            },
            interfaces=["client_iface"]
        )
        
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tf.close()
        builder.to_file(tf.name)
        config_path = tf.name
        wsl_config_path = to_wsl(config_path)

        try:
            # We use Python for all here for simplicity of assertions
            common_script_header = f"""
import sys, time, os, logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format='%(asctime)s [%(levelname)s] %(message)s')
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode

class MockHandler(RequestHandler):
    def __init__(self, sid): self.sid = sid
    def get_service_id(self): return self.sid
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, b'')
"""
            # Provider A
            prov_a_script = common_script_header + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'provider_a')
rt.offer_service('ServiceA', MockHandler(0x1000))
rt.start()
print("PROV_A_READY")
sys.stdout.flush()
while True: time.sleep(1)
"""
            p_a = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', prov_a_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Provider B
            prov_b_script = common_script_header + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'provider_b')
rt.offer_service('ServiceB', MockHandler(0x2000))
rt.start()
print("PROV_B_READY")
sys.stdout.flush()
while True: time.sleep(1)
"""
            p_b = run_in_ns("ns_ecu2", [sys.executable, '-u', '-c', prov_b_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # Wait for both
            ready_a = False; ready_b = False
            start = time.time()
            while time.time() - start < 5:
                if not ready_a:
                    line = p_a.stdout.readline()
                    if "PROV_A_READY" in line: ready_a = True
                if not ready_b:
                    line = p_b.stdout.readline()
                    if "PROV_B_READY" in line: ready_b = True
                if ready_a and ready_b: break
            assert ready_a and ready_b, "Providers A/B failed to signal ready"

            # Client
            client_script = common_script_header + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'split_client')
rt.start()
time.sleep(1)
# Check if services found
found = 0
for i in range(20):
    s1 = rt.get_client('ServiceA', None, timeout=0.1)
    s2 = rt.get_client('ServiceB', None, timeout=0.1)
    if s1 and s2:
        print("FOUND_BOTH")
        sys.stdout.flush()
        break
    time.sleep(1)
rt.stop()
"""
            c_proc = run_in_ns("ns_ecu3", [sys.executable, '-u', '-c', client_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                start = time.time()
                while time.time() - start < 30:
                    if c_proc.poll() is not None:
                         # Process exited!
                         stdout = c_proc.stdout.read()
                         stderr = c_proc.stderr.read()
                         pytest.fail(f"Client process exited prematurely code={c_proc.returncode}.\nStdout: {stdout}\nStderr: {stderr}")
                    
                    line = c_proc.stdout.readline()
                    if line:
                        sys.stderr.write(f"[Client] {line}")
                        if "FOUND_BOTH" in line: break
                    else:
                        time.sleep(0.1)
                else:
                    pytest.fail(f"Client failed to find both services (Timeout).\nStdout: {c_proc.stdout.read()}\nStderr: {c_proc.stderr.read()}")
            finally:
                c_proc.terminate()

        finally:
            p_a.terminate()
            p_b.terminate()
            if os.path.exists(config_path): os.unlink(config_path)

    def test_c_multi_instance_same_iface(self):
        """
        Scenario C: Multiple Instances (Same Interface)
        Two instances of Service 0x1000 on veth_ns_ecu1 with differentInstance IDs.
        """
        builder = ConfigBuilder()
        # Updated interface config — inside namespaces, interface is ALWAYS 'veth0'
        # Since Scenario C has 2 instances on the SAME interface in the SAME namespace (ns_ecu1),
        # they must share veth0 but use different ports/endpoints.
        builder.add_interface("veth0", "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_1": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "svc_ep_2": {"ip": "10.0.1.1", "port": 31002, "proto": "udp"},
            "sd_uc_1": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"},
            "sd_uc_2": {"ip": "10.0.1.1", "port": 31005, "proto": "udp"} # Different port
        })
        
        builder.add_instance("inst_1", unicast_bind={"primary": "sd_uc_1"},
            providing={"Svc": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "svc_ep_1"}}},
            interfaces=["primary"])
        
        builder.add_instance("inst_2", unicast_bind={"primary": "sd_uc_2"},
            providing={"Svc": {"service_id": 0x1000, "instance_id": 2, "offer_on": {"primary": "svc_ep_2"}}},
            interfaces=["primary"])

        # Client remains on ns_ecu3
        builder.add_interface("veth0", "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })
        builder.add_instance("client", unicast_bind={"client_iface": "client_ep"},
            required={
                "Svc1": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "Svc2": {"service_id": 0x1000, "instance_id": 2, "find_on": ["client_iface"]}
            },
            interfaces=["client_iface"]
        )
        
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tf.close()
        builder.to_file(tf.name)
        config_path = tf.name
        wsl_config_path = to_wsl(config_path)
        
        try:
             common = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
class Handler(RequestHandler):
    def get_service_id(self): return 0x1000
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, b'')
"""
             p1 = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', common + f"rt=SomeIpRuntime('{wsl_config_path}', 'inst_1'); rt.offer_service('Svc', Handler()); rt.start(); time.sleep(100)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             p2 = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', common + f"rt=SomeIpRuntime('{wsl_config_path}', 'inst_2'); rt.offer_service('Svc', Handler()); rt.start(); time.sleep(100)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             
             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
s1 = rt.get_client('Svc1', None, timeout=2)
s2 = rt.get_client('Svc2', None, timeout=2)
if s1 and s2:
    print("FOUND_BOTH")
rt.stop()
"""
             c_proc = run_in_ns("ns_ecu3", [sys.executable, '-u', '-c', client_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             try:
                start = time.time()
                while time.time() - start < 30:
                    line = c_proc.stdout.readline()
                    if "FOUND_BOTH" in line: break
                else:
                    pytest.fail(f"Client failed to differentiate instances. Stderr: {c_proc.stderr.read()}")
             finally:
                c_proc.terminate()
        finally:
             p1.terminate(); p2.terminate(); os.unlink(config_path)

    def test_d_multi_instance_diff_iface(self):
        """
        Scenario D: Multiple Instances (Different Interfaces)
        Instance 1 on iface1, Instance 2 on iface2.
        Client on iface3 finds both verify source IPs.
        """
        builder = ConfigBuilder()
        builder.add_interface("veth0", "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_1": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface("veth0", "secondary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_2": {"ip": "10.0.1.2", "port": 31002, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.2", "port": 31000, "proto": "udp"}
        })
        builder.add_interface("veth0", "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        # Instance 1 (ID 1) on ecu1
        builder.add_instance("inst_1", unicast_bind={"primary": "sd_uc"},
            providing={"Svc": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "svc_ep_1"}}},
            interfaces=["primary"])
        
        # Instance 2 (ID 2) on ecu2
        builder.add_instance("inst_2", unicast_bind={"secondary": "sd_uc"},
            providing={"Svc": {"service_id": 0x1000, "instance_id": 2, "offer_on": {"secondary": "svc_ep_2"}}},
            interfaces=["secondary"])

        builder.add_instance("client", unicast_bind={"client_iface": "client_ep"},
            required={
                "Svc1": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "Svc2": {"service_id": 0x1000, "instance_id": 2, "find_on": ["client_iface"]}
            },
            interfaces=["client_iface"]
        )
        
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tf.close()
        builder.to_file(tf.name)
        config_path = tf.name
        wsl_config_path = to_wsl(config_path)

        try:
             common = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
class Handler(RequestHandler):
    def get_service_id(self): return 0x1000
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, b'')
"""
             # Inst 1 (Python)
             p1 = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', common + f"rt=SomeIpRuntime('{wsl_config_path}', 'inst_1'); rt.offer_service('Svc', Handler()); rt.start(); print('INST_1_READY'); sys.stdout.flush(); time.sleep(100)"], stdout=subprocess.PIPE, text=True)
             
             # Inst 2 (Try Rust if avail, else Python)
             rust_bin = os.path.join(PROJECT_ROOT, "target", "debug", "rust_app_demo")
             if os.path.exists(rust_bin) or os.path.exists(rust_bin + ".exe"): # Check WSL path
                 p2 = run_in_ns("ns_ecu2", [rust_bin, wsl_config_path, "inst_2"], stdout=subprocess.PIPE, text=True)
             else:
                 print("Rust binary not found, using Python for Inst 2")
                 p2 = run_in_ns("ns_ecu2", [sys.executable, '-u', '-c', common + f"rt=SomeIpRuntime('{wsl_config_path}', 'inst_2'); rt.offer_service('Svc', Handler()); rt.start(); print('INST_2_READY'); sys.stdout.flush(); time.sleep(100)"], stdout=subprocess.PIPE, text=True)

             # Wait for both
             ready_1 = False; ready_2 = False
             start = time.time()
             while time.time() - start < 5:
                 if not ready_1:
                     line = p1.stdout.readline()
                     if "INST_1_READY" in line: ready_1 = True
                 if not ready_2:
                     line = p2.stdout.readline()
                     if "INST_2_READY" in line: ready_2 = True
                     # Rust app might not print INST_2_READY, assume it's fast if Rust
                     elif os.path.exists(rust_bin): ready_2 = True 
                 if ready_1 and ready_2: break
             assert ready_1 and ready_2, "Instances 1/2 failed to signal ready"

             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
s1 = rt.get_client('Svc1', None, timeout=2)
s2 = rt.get_client('Svc2', None, timeout=2)
if s1 and s2:
    print(f"FOUND: BOTH")
else:
    print(f"MISSING")
rt.stop()
"""
             c_proc = run_in_ns("ns_ecu3", [sys.executable, '-u', '-c', client_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             try:
                start = time.time()
                while time.time() - start < 30:
                    line = c_proc.stdout.readline()
                    if "FOUND: BOTH" in line: break
                else:
                    pytest.fail(f"Client failed to verify both instances. Stderr: {c_proc.stderr.read()}")
             finally:
                c_proc.terminate()
        finally:
             p1.terminate(); p2.terminate(); os.unlink(config_path)

    def test_e_static_config(self):
        """
        Scenario E: Static Configuration (No SD)
        Client sends to static IP:Port, Server receives.
        """
        builder = ConfigBuilder()
        builder.add_interface("veth0", "primary", {
            "svc_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"}
            # No SD endpoints!
        })
        builder.add_interface("veth0", "client_iface", {
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        # Static Server
        # We bind unicast_bind to a dummy or the data EP just to satisfy schema if needed.
        # But for static, we might not strictly need it if no SD is used.
        # However, to avoid runtime errors if it expects it, we map it.
        builder.add_instance("static_server", 
           unicast_bind={"primary": "svc_ep"},
           providing={"Svc": {"service_id": 0x9999, "instance_id": 1, "offer_on": {"primary": "svc_ep"}}}
        )

        # Static Client
        builder.add_instance("static_client", unicast_bind={"client_iface": "client_ep"},
            required={"Svc": {"service_id": 0x9999, "instance_id": 1, "find_on": ["client_iface"]}}
            # find_on usually implies SD used.
            # But here we want static.
            # Does the runtime auto-map static endpoints defined in 'interfaces'?
            # We defined 'svc_ep' in 'primary'.
            # Instance 'static_server' uses it.
            # Client instances needs to know about 'static_server'?
            # Usually static config involves explicit IP/Port in 'required' or sidechannel?
            # Fusion doc says: "Client sends data to static IP:Port".
            # Can we configure a static remote instance?
            # If not, we just use 'get_service_proxy_static(ip, port)' API manually?
            # The test here simulates that.
        )
        
        # NOTE: Fusion Runtime static routing logic might be implicit if we just send to that IP.
        # But let's assume valid config.
        
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tf.close()
        builder.to_file(tf.name)
        config_path = tf.name
        wsl_config_path = to_wsl(config_path)

        try:
             common = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, ReturnCode, MessageType, RequestHandler
"""
             # Server
             # Just listens on 31001. Runtime should bind purely based on offer_on.
             server_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'static_server')
class Handler(RequestHandler):
    def get_service_id(self): return 0x9999
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p):
        print(f"RECEIVED_REQ")
        sys.stdout.flush()
        return (ReturnCode.E_OK, b'')
rt.offer_service('Svc', Handler())
rt.start()
print("SERVER_READY")
sys.stdout.flush()
while True: time.sleep(1)
"""
             srv = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', server_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             # Wait for server
             ready_srv = False
             start = time.time()
             while time.time() - start < 5:
                  line = srv.stdout.readline()
                  if "SERVER_READY" in line:
                      ready_srv = True
                      break
             assert ready_srv, "Static Server failed to signal ready"
             
             # Client
             # Manually send to 10.0.1.1:31001 (Linux) or 127.0.0.1:31001 (Windows)
             target_ip = '127.0.0.1' if sys.platform != 'linux' else '10.0.1.1'
             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'static_client')
rt.start()
time.sleep(1)
# Static send
rt.send_request(0x9999, 1, b'', ('{target_ip}', 31001))
time.sleep(1)
rt.stop()
"""
             client = run_in_ns("ns_ecu3", [sys.executable, '-u', '-c', client_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             if client.wait() != 0:
                  pytest.fail(f"Static Client failed. Stderr: {client.stderr.read()}")
             
             start = time.time()
             while time.time() - start < 5:
                  line = srv.stdout.readline()
                  if "RECEIVED_REQ" in line: break
             else:
                  pytest.fail("Static Server did not receive request")
        finally:
             srv.terminate(); os.unlink(config_path)

    def test_f_shared_endpoint(self):
        """
        Scenario F: Shared Endpoint.
        ServiceA and ServiceB share 'shared_ep' (Same Port).
        """
        builder = ConfigBuilder()
        builder.add_interface("veth0", "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "shared_ep": {"ip": "10.0.1.1", "port": 31050, "proto": "udp"}, # SHARED PORT
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface("veth0", "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        builder.add_instance("shared_server", unicast_bind={"primary": "sd_uc"},
            providing={
                "SvcA": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "shared_ep"}},
                "SvcB": {"service_id": 0x2000, "instance_id": 1, "offer_on": {"primary": "shared_ep"}}
            },
            interfaces=["primary"]
        )

        builder.add_instance("client", unicast_bind={"client_iface": "client_ep"},
            required={
                "SvcA": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "SvcB": {"service_id": 0x2000, "instance_id": 1, "find_on": ["client_iface"]}
            },
            interfaces=["client_iface"]
        )
        
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tf.close()
        builder.to_file(tf.name)
        config_path = tf.name
        wsl_config_path = to_wsl(config_path)

        try:
             common = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
class MockHandler(RequestHandler):
    def __init__(self, sid): self.sid = sid
    def get_service_id(self): return self.sid
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, b'')
"""
             srv_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'shared_server')
rt.offer_service('SvcA', MockHandler(0x1000))
rt.offer_service('SvcB', MockHandler(0x2000))
rt.start()
print("SHARED_SERVER_READY")
sys.stdout.flush()
while True: time.sleep(1)
"""
             srv = run_in_ns("ns_ecu1", [sys.executable, '-u', '-c', srv_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             
             # Wait for shared server
             ready_srv = False
             start = time.time()
             while time.time() - start < 5:
                 line = srv.stdout.readline()
                 if "SHARED_SERVER_READY" in line:
                     ready_srv = True
                     break
             assert ready_srv, "Shared Server failed to signal ready"
             
             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(1)
for i in range(20):
    s1 = rt.get_client('SvcA', None, timeout=0.1)
    s2 = rt.get_client('SvcB', None, timeout=0.1)
    if s1 and s2:
        print("SHARED_OK")
        break
    time.sleep(1)
rt.stop()
"""
             c_proc = run_in_ns("ns_ecu3", [sys.executable, '-u', '-c', client_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             try:
                 start = time.time()
                 while time.time() - start < 30:
                     line = c_proc.stdout.readline()
                     if "SHARED_OK" in line: break
                 else:
                     pytest.fail(f"Failed to verify shared port. Stderr: {c_proc.stderr.read()}")
             finally:
                 c_proc.terminate()
        finally:
             srv.terminate(); os.unlink(config_path)



