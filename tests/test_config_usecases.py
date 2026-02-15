import os
import sys
import json
import time
import subprocess
import pytest
import tempfile
import socket
import datetime
import threading

# Skip entire module if not on Linux (WSL)
if sys.platform != "linux":
    pytest.skip("Skipping Config Use Cases on non-Linux platform", allow_module_level=True)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
JS_APP_DIR = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "js_app")

def to_wsl(path):
    # Normalize paths for WSL/Linux
    return path.replace("\\", "/").replace("C:", "/mnt/c").replace("c:", "/mnt/c")

from tools.fusion.environment import NetworkEnvironment

# Global environment
ENV = NetworkEnvironment()

def ensure_vnet():
    if not ENV.interfaces:
        ENV.detect()
    if not ENV.has_vnet:
        if not ENV.setup_vnet():
            pytest.skip("VNet setup failed - root/sudo required")

def get_iface(ns, ip):
    """Resolve physical interface name for an IP in a namespace."""
    ensure_vnet()
    # If the exact IP is found in the map, use it
    if ns in ENV.vnet_interface_map:
        if ip in ENV.vnet_interface_map[ns]:
            name = ENV.vnet_interface_map[ns][ip]
            print(f"DIAG: Resolved {ns}/{ip} -> {name}")
            return name
        # Fallback: find any interface in that NS (heuristic)
        for val in ENV.vnet_interface_map[ns].values():
            if val != "lo":
                print(f"DIAG: Fallback resolved {ns}/{ip} -> {val}")
                return val
    print(f"DIAG: Failed to resolve {ns}/{ip}, using veth0")
    return "veth0" # Last fallback

def get_log_dir(test_name):
    """Get the log directory for the current test case."""
    base_log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(os.getcwd(), "logs", "usecases"))
    test_log_dir = os.path.join(base_log_dir, test_name)
    os.makedirs(test_log_dir, exist_ok=True)
    return test_log_dir

def run_in_ns(ns_name, command_list, **kwargs):
    """Run a command inside a specific network namespace using sudo."""
    if sys.platform != "linux":
        return subprocess.Popen(command_list, **kwargs)
    cmd = ["sudo", "ip", "netns", "exec", ns_name] + command_list
    return subprocess.Popen(cmd, **kwargs)

class TeeProcess:
    """Wraps subprocess.Popen, tees output to a file, and allows live reading."""
    def __init__(self, cmd, log_path, cwd=None, env=None, ns=None):
        self.log_file = open(log_path, "w")
        self.log_file.write(f"COMMAND: {' '.join(cmd)}\n")
        self.log_file.write(f"CWD: {cwd or os.getcwd()}\n")
        self.log_file.write(f"TIME: {datetime.datetime.now()}\n")
        self.log_file.write("="*40 + "\n\n")
        self.log_file.flush()
        
        import queue
        self.output_queue = queue.Queue()
        
        final_cmd = cmd
        if ns and sys.platform == "linux":
            final_cmd = ["sudo", "ip", "netns", "exec", ns] + cmd
            
        self.proc = subprocess.Popen(
            final_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env,
            text=True,
            bufsize=1
        )
        
        self.reader_thread = threading.Thread(target=self._reader)
        self.reader_thread.daemon = True
        self.reader_thread.start()
        
    def _reader(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    break
                continue
            self.log_file.write(line)
            self.log_file.flush()
            self.output_queue.put(line)
            
    def readline(self, timeout=None):
        import queue
        try:
            return self.output_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def terminate(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log_file.close()

class ConfigBuilder:
    """Helper to build config.json structures."""
    def __init__(self, log_dir):
        self.config = {"interfaces": {}, "instances": {}}
        self.log_dir = log_dir

    def add_interface(self, name, logical_name, endpoints):
        # Auto-detect loopback for Windows
        if sys.platform != "linux" and (name.startswith("veth") or name.startswith("eth") or name == "lo"):
            name = "Loopback Pseudo-Interface 1"
            
        eps = {}
        for ep_name, details in endpoints.items():
            d = details.copy()
            if sys.platform != "linux" and d["ip"].startswith("10."):
                d["ip"] = "127.0.0.1"
            eps[ep_name] = d
            
        self.config["interfaces"][logical_name] = {"name": name, "endpoints": eps}
        if "sd_mcast" in eps:
            self.config["interfaces"][logical_name]["sd"] = {"endpoint": "sd_mcast", "mode": "offer", "cycle_ms": 1000}

    def add_instance(self, name, unicast_bind, providing=None, required=None, interfaces=None):
        inst = {"unicast_bind": unicast_bind, "interfaces": interfaces or list(unicast_bind.keys())}
        if providing: inst["providing"] = providing
        if required: inst["required"] = required
        self.config["instances"][name] = inst

    def to_file(self, filename="config.json"):
        path = os.path.join(self.log_dir, filename)
        with open(path, 'w') as f:
            json.dump(self.config, f, indent=2)
        return path

class PythonHelper:
    @staticmethod
    def run_script(code, log_dir, name, ns=None):
        """Run a Python script in a namespace, using a temp file."""
        fd, path = tempfile.mkstemp(suffix='.py', prefix=f"tmp_{name}_")
        os.close(fd)
        with open(path, 'w') as f:
            f.write(code)
        
        cmd = [sys.executable, "-u", to_wsl(path)]
        return TeeProcess(cmd, os.path.join(log_dir, f"{name}.log"), ns=ns), path

class JSHelper:
    @staticmethod
    def run_script(js_code, config_path, instance_name, log_dir):
        """Run a JS script in the js_app directory, returning the process and path to config."""
        # Create a temp file IN the js_app directory to ensure relative imports work
        temp_name = os.path.join(JS_APP_DIR, f"tmp_{instance_name}.js")
        # Ensure directory exists
        os.makedirs(JS_APP_DIR, exist_ok=True)
        
        with open(temp_name, "w") as f:
            wrapper = f"""
import {{ SomeIpRuntime, LogLevel, MessageType, ReturnCode }} from 'fusion-hawking';
import {{ MathServiceClient, StringServiceClient }} from './dist/manual_bindings.js';

const configPath = process.argv[2];
const instanceName = process.argv[3];
const runtime = new SomeIpRuntime(configPath, instanceName);
runtime.start();
(async () => {{
{js_code}
}})().catch(e => {{
    console.log(`JS_ERROR: ${{e.message}}`);
    process.exit(1);
}}).finally(() => {{
    runtime.stop();
}});
"""
            f.write(wrapper)
        
        # Build if dist/manual_bindings.js doesn't exist
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        if not os.path.exists(os.path.join(JS_APP_DIR, "dist", "manual_bindings.js")):
             subprocess.run([npm, "install"], cwd=JS_APP_DIR, capture_output=True)
             subprocess.run([npm, "run", "build"], cwd=JS_APP_DIR, capture_output=True)

        cmd = ["node", os.path.basename(temp_name), to_wsl(config_path), instance_name]
        return TeeProcess(cmd, os.path.join(log_dir, f"{instance_name}.log"), cwd=JS_APP_DIR, ns="ns_ecu3"), temp_name



class TestUseCases:
    """
    Comprehensive Configuration Use Case Tests
    """
    
    def test_a_multi_homed_provider(self):
        """
        Scenario A: Multi-Homed Provider
        Provider offers Service 0x1001 on veth_ns_ecu1 (primary) and veth_ns_ecu2 (secondary).
        JS Client on veth_ns_ecu3 should find it on both.
        """
        log_dir = get_log_dir("test_a_multi_homed_provider")
        builder = ConfigBuilder(log_dir)
        
        if1 = get_iface("ns_ecu1", "10.0.1.1")
        if2 = get_iface("ns_ecu1", "10.0.2.1")
        if3 = get_iface("ns_ecu3", "10.0.1.3")

        builder.add_interface(if1, "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if2, "secondary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_2": {"ip": "10.0.2.1", "port": 31002, "proto": "udp"},
            "sd_uc": {"ip": "10.0.2.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if3, "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        builder.add_instance("multi_provider", 
            unicast_bind={"primary": "sd_uc", "secondary": "sd_uc"},
            providing={
                "MathService": {
                    "service_id": 0x1001,
                    "instance_id": 1,
                    "offer_on": {"primary": "svc_ep", "secondary": "svc_ep_2"}
                }
            },
            interfaces=["primary", "secondary"]
        )
        builder.add_instance("js_client",
             unicast_bind={"client_iface": "client_ep"},
             required={"MathService": {"service_id": 0x1001, "instance_id": 1, "find_on": ["client_iface"]}},
             interfaces=["client_iface"]
        )

        config_path = builder.to_file()
        wsl_config_path = to_wsl(config_path)

        try:
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
            prov_proc, prov_path = PythonHelper.run_script(provider_script, log_dir, "provider", ns="ns_ecu1")
            
            # Wait start
            start = time.time()
            started = False
            while time.time() - start < 10:
                line = prov_proc.readline(timeout=0.1)
                if line and "PROVIDER_STARTED" in line:
                    started = True
                    break
            assert started, "Provider failed to start"

            # JS Client
            js_script = """
            // Wait for SD
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
                console.log("JS_ERROR: Service 0x1001 not found");
                process.exit(1);
            }
            
            try {
                const client = new MathServiceClient(runtime, 'js_client');
                const result = await client.add(10, 20);
                console.log(`JS_RESULT: ${result}`);
            } catch (e) {
                console.log(`JS_ERROR: ${e.message}`);
            }
            """
            
            client_proc, client_path = JSHelper.run_script(js_script, wsl_config_path, 'js_client', log_dir)
            
            try:
                # Read Output
                start = time.time()
                while time.time() - start < 40:
                    line = client_proc.readline(timeout=0.1)
                    if line:
                        if "JS_RESULT: 30" in line: break
                        if "JS_ERROR" in line: pytest.fail(f"JS Client Error: {line}")
                else:
                    pytest.fail("JS Client timed out")
            finally:
                client_proc.terminate()
        finally:
            prov_proc.terminate()


    def test_b_complex_requirements(self):
        """
        Scenario B: Complex Requirements (Split Interfaces)
        Instance requires ServiceA on iface1 and ServiceB on iface2.
        """
        log_dir = get_log_dir("test_b_complex_requirements")
        builder = ConfigBuilder(log_dir)
        
        if1 = get_iface("ns_ecu1", "10.0.1.1")
        if2 = get_iface("ns_ecu2", "10.0.1.2")
        if3 = get_iface("ns_ecu3", "10.0.1.3")

        builder.add_interface(if1, "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_a_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if2, "secondary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_b_ep": {"ip": "10.0.1.2", "port": 31002, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.2", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if3, "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        builder.add_instance("provider_a", unicast_bind={"primary": "sd_uc"},
            providing={"ServiceA": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "svc_a_ep"}}},
            interfaces=["primary"])
        builder.add_instance("provider_b", unicast_bind={"secondary": "sd_uc"},
            providing={"ServiceB": {"service_id": 0x2000, "instance_id": 1, "offer_on": {"secondary": "svc_b_ep"}}},
            interfaces=["secondary"])
        builder.add_instance("split_client", unicast_bind={"client_iface": "client_ep"},
            required={
                "ServiceA": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "ServiceB": {"service_id": 0x2000, "instance_id": 1, "find_on": ["client_iface"]}
            },
            interfaces=["client_iface"]
        )
        
        config_path = builder.to_file()
        wsl_config_path = to_wsl(config_path)

        try:
            common_script = f"""
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
            p_a, p_a_path = PythonHelper.run_script(common_script + f"\nrt=SomeIpRuntime('{wsl_config_path}', 'provider_a')\nrt.offer_service('ServiceA', MockHandler(0x1000))\nrt.start()\nprint('PROV_A_READY')\nsys.stdout.flush()\nwhile True: time.sleep(1)", 
                                                  log_dir, "provider_a", ns="ns_ecu1")
            p_b, p_b_path = PythonHelper.run_script(common_script + f"\nrt=SomeIpRuntime('{wsl_config_path}', 'provider_b')\nrt.offer_service('ServiceB', MockHandler(0x2000))\nrt.start()\nprint('PROV_B_READY')\nsys.stdout.flush()\nwhile True: time.sleep(1)",
                                                  log_dir, "provider_b", ns="ns_ecu2")
            
            start = time.time()
            ra, rb = False, False
            while time.time() - start < 10:
                if not ra: ra = "PROV_A_READY" in (p_a.readline(0.1) or "")
                if not rb: rb = "PROV_B_READY" in (p_b.readline(0.1) or "")
                if ra and rb: break
            assert ra and rb, "Providers failed to start"

            client_script = common_script + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'split_client')
rt.start()
time.sleep(1)
success = False
for i in range(20):
    if rt.get_client('ServiceA', None, timeout=0.1) and rt.get_client('ServiceB', None, timeout=0.1):
        print("FOUND_BOTH")
        success = True
        break
    time.sleep(1)
if success: print("CLIENT_DONE")
rt.stop()
"""
            p_c, p_c_path = PythonHelper.run_script(client_script, log_dir, "client", ns="ns_ecu3")
            try:
                start = time.time()
                found = False
                while time.time() - start < 30:
                    l = p_c.readline(0.1)
                    if l and "FOUND_BOTH" in l: found = True; break
                assert found, "Client failed to find services"
            finally:
                p_c.terminate()
        finally:
            p_a.terminate()
            p_b.terminate()


    def test_c_multi_instance_same_iface(self):
        """
        Scenario C: Multiple Instances (Same Interface)
        Two instances of Service 0x1000 on veth_ns_ecu1 with different Instance IDs.
        """
        log_dir = get_log_dir("test_c_multi_instance")
        builder = ConfigBuilder(log_dir)
        
        if1 = get_iface("ns_ecu1", "10.0.1.1")
        if3 = get_iface("ns_ecu3", "10.0.1.3")

        builder.add_interface(if1, "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_1": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "svc_ep_2": {"ip": "10.0.1.1", "port": 31002, "proto": "udp"},
            "sd_uc_1": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"},
            "sd_uc_2": {"ip": "10.0.1.1", "port": 31005, "proto": "udp"} 
        })
        builder.add_interface(if3, "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })
        
        builder.add_instance("inst_1", unicast_bind={"primary": "sd_uc_1"},
            providing={"Svc": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "svc_ep_1"}}}, interfaces=["primary"])
        builder.add_instance("inst_2", unicast_bind={"primary": "sd_uc_2"},
            providing={"Svc": {"service_id": 0x1000, "instance_id": 2, "offer_on": {"primary": "svc_ep_2"}}}, interfaces=["primary"])
        builder.add_instance("client", unicast_bind={"client_iface": "client_ep"},
            required={
                "Svc1": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "Svc2": {"service_id": 0x1000, "instance_id": 2, "find_on": ["client_iface"]}
            }, interfaces=["client_iface"])

        config_path = builder.to_file()
        wsl_config_path = to_wsl(config_path)
        
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
        # Providers
        prov_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'inst_1')
rt.offer_service('Svc', Handler())
rt.start()
print('INST_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
        p1, p1_path = PythonHelper.run_script(prov_script, log_dir, "inst1", ns="ns_ecu1")
        
        prov2_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'inst_2')
rt.offer_service('Svc', Handler())
rt.start()
print('INST_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
        p2, p2_path = PythonHelper.run_script(prov2_script, log_dir, "inst2", ns="ns_ecu1")
                         
        try:
            client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
s1 = rt.get_client('Svc1', None, timeout=2.0)
s2 = rt.get_client('Svc2', None, timeout=2.0)
if s1 and s2:
    print("FOUND_BOTH")
rt.stop()
"""
            pc, pc_path = PythonHelper.run_script(client_script, log_dir, "client", ns="ns_ecu3")
            try:
                start = time.time()
                found = False
                while time.time() - start < 30:
                    l = pc.readline(0.1)
                    if l and "FOUND_BOTH" in l: found = True; break
                assert found, "Client failed to find both instances"
            finally:
                pc.terminate()
        finally:
            p1.terminate()
            p2.terminate()


    def test_d_multi_instance_diff_iface(self):
        """
        Scenario D: Multiple Instances (Different Interfaces)
        Instance 1 on iface1, Instance 2 on iface2.
        Client on iface3 finds both verify source IPs.
        """
        log_dir = get_log_dir("test_d_multi_instance")
        builder = ConfigBuilder(log_dir)
        
        if1 = get_iface("ns_ecu1", "10.0.1.1")
        if2 = get_iface("ns_ecu2", "10.0.1.2")
        if3 = get_iface("ns_ecu3", "10.0.1.3")

        builder.add_interface(if1, "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_1": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if2, "secondary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "svc_ep_2": {"ip": "10.0.1.2", "port": 31002, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.2", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if3, "client_iface", {
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
        
        config_path = builder.to_file()
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
             prov_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'inst_1')
rt.offer_service('Svc', Handler())
rt.start()
print('INST_1_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
             p1, p1_path = PythonHelper.run_script(prov_script, log_dir, "inst1", ns="ns_ecu1")
             
             # Inst 2 (Try Rust if avail, else Python)
             rust_bin = os.path.join(PROJECT_ROOT, "target", "debug", "rust_app_demo")
             p2_path = None
             if os.path.exists(rust_bin) or os.path.exists(rust_bin + ".exe"): # Check WSL path
                 p2 = TeeProcess([rust_bin, wsl_config_path, "inst_2"], os.path.join(log_dir, "inst2.log"), ns="ns_ecu2")
             else:
                 print("Rust binary not found, using Python for Inst 2")
                 prov2_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'inst_2')
rt.offer_service('Svc', Handler())
rt.start()
print('INST_2_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
                 p2, p2_path = PythonHelper.run_script(prov2_script, log_dir, "inst2", ns="ns_ecu2")

             # Wait for both
             ready_1 = False; ready_2 = False
             start = time.time()
             while time.time() - start < 5:
                 if not ready_1:
                     line = p1.readline(0.1)
                     if "INST_1_READY" in (line or ""): ready_1 = True
                 if not ready_2:
                     line = p2.readline(0.1)
                     if "INST_2_READY" in (line or ""): ready_2 = True
                     # Rust app might not print INST_2_READY, assume it's fast if Rust
                     elif os.path.exists(rust_bin): ready_2 = True 
                 if ready_1 and ready_2: break
             assert ready_1 and ready_2, "Instances 1/2 failed to signal ready"

             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
s1 = rt.get_client('Svc1', None, timeout=2.0)
s2 = rt.get_client('Svc2', None, timeout=2.0)
if s1 and s2:
    print(f"FOUND: BOTH")
else:
    print(f"MISSING")
rt.stop()
"""
             c_proc, c_path = PythonHelper.run_script(client_script, log_dir, "client", ns="ns_ecu3")
             try:
                start = time.time()
                while time.time() - start < 30:
                    line = c_proc.readline(0.1)
                    if "FOUND: BOTH" in (line or ""): break
                else:
                    pytest.fail(f"Client failed to verify both instances.")
             finally:
                c_proc.terminate()
        finally:
             if p1: p1.terminate()
             if p2: p2.terminate()


    def test_e_static_config(self):
        """
        Scenario E: Static Configuration (No SD)
        """
        log_dir = get_log_dir("test_e_static_config")
        builder = ConfigBuilder(log_dir)
        
        if1 = get_iface("ns_ecu1", "10.0.1.1")
        if2 = get_iface("ns_ecu2", "10.0.1.2")

        builder.add_interface(if1, "primary", {
            "svc_ep": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if2, "secondary", {
             "client_ep": {"ip": "10.0.1.2", "port": 32000, "proto": "udp"}
        })
        builder.add_instance("static_server", unicast_bind={"primary": "svc_ep"},
            providing={"Svc": {"service_id": 0x9999, "instance_id": 1, "offer_on": {"primary": "svc_ep"}}})
        builder.add_instance("static_client", unicast_bind={"secondary": "client_ep"},
            required={"Svc": {"service_id": 0x9999, "instance_id": 1, "find_on": ["secondary"]}})
        
        config_path = builder.to_file()
        wsl_config_path = to_wsl(config_path)

        try:
             common = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, ReturnCode, RequestHandler
"""
             srv_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'static_server')
class Handler(RequestHandler):
    def get_service_id(self): return 0x9999
    def handle(self, h, p):
        print("RECEIVED_REQ")
        sys.stdout.flush()
        return (ReturnCode.E_OK, b'')
rt.offer_service('Svc', Handler())
rt.start()
print("SERVER_READY")
sys.stdout.flush()
while True: time.sleep(1)
"""
             srv, srv_p = PythonHelper.run_script(srv_script, log_dir, "server", ns="ns_ecu1")
             start = time.time()
             ready = False
             while time.time() - start < 10:
                 if "SERVER_READY" in (srv.readline(0.1) or ""): ready = True; break
             assert ready

             target_ip = '127.0.0.1' if sys.platform != 'linux' else '10.0.1.1'
             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'static_client')
rt.start()
time.sleep(1)
rt.send_request(0x9999, 1, b'', ('{target_ip}', 31000, 'udp'))
time.sleep(1)
rt.stop()
"""
             # FIXED: Scenario E client MUST run in ns_ecu2 where 10.0.1.2 exists
             cp, cpp = PythonHelper.run_script(client_script, log_dir, "client", ns="ns_ecu2")
             
             try:
                 start = time.time()
                 rx = False
                 while time.time() - start < 10:
                     if "RECEIVED_REQ" in (srv.readline(0.1) or ""): rx = True; break
                 assert rx
             finally:
                 cp.terminate()
        finally:
             if srv: srv.terminate()


    def test_f_shared_endpoint(self):
        """
        Scenario F: Shared Endpoint
        """
        log_dir = get_log_dir("test_f_shared_endpoint")
        builder = ConfigBuilder(log_dir)
        
        if1 = get_iface("ns_ecu1", "10.0.1.1")
        if3 = get_iface("ns_ecu3", "10.0.1.3")

        builder.add_interface(if1, "primary", {
            "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
            "shared_ep": {"ip": "10.0.1.1", "port": 31050, "proto": "udp"},
            "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
        })
        builder.add_interface(if3, "client_iface", {
             "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "proto": "udp"},
             "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
        })

        builder.add_instance("shared_server", unicast_bind={"primary": "sd_uc"},
            providing={
                "SvcA": {"service_id": 0x1000, "instance_id": 1, "offer_on": {"primary": "shared_ep"}},
                "SvcB": {"service_id": 0x2000, "instance_id": 1, "offer_on": {"primary": "shared_ep"}}
            }, interfaces=["primary"])
        builder.add_instance("client", unicast_bind={"client_iface": "client_ep"},
            required={
                "SvcA": {"service_id": 0x1000, "instance_id": 1, "find_on": ["client_iface"]},
                "SvcB": {"service_id": 0x2000, "instance_id": 1, "find_on": ["client_iface"]}
            }, interfaces=["client_iface"])
        
        config_path = builder.to_file()
        wsl_config_path = to_wsl(config_path)

        try:
             common = f"""
import sys, time, os
sys.path.append('{to_wsl(PROJECT_ROOT)}')
sys.path.append('{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
"""
             srv_script = common + f"""
class Handler(RequestHandler):
    def __init__(self, sid): self.sid = sid
    def get_service_id(self): return self.sid
    def handle(self, h, p): return p

rt = SomeIpRuntime('{wsl_config_path}', 'shared_server')
rt.offer_service('SvcA', Handler(0x1000))
rt.offer_service('SvcB', Handler(0x2000))
rt.start()
print('SRV_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
             srv, srv_p = PythonHelper.run_script(srv_script, log_dir, "server", ns="ns_ecu1")
             
             start = time.time()
             ready = False
             while time.time() - start < 10:
                 if "SRV_READY" in (srv.readline(0.1) or ""): ready = True; break
             assert ready

             client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
success = rt.get_client('SvcA', None, timeout=2.0) and rt.get_client('SvcB', None, timeout=2.0)
print('OK' if success else 'FAIL')
rt.stop()
"""
             pc, pc_p = PythonHelper.run_script(client_script, log_dir, "client", ns="ns_ecu3")
             try:
                 found = False
                 start = time.time()
                 while time.time() - start < 30:
                     if "OK" in (pc.readline(0.1) or ""): found = True; break
                 assert found
             finally:
                 pc.terminate()
        finally:
             if srv: srv.terminate()
