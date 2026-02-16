"""
Configuration Use-Case Tests (VNet-Only)

These tests exercise specific multi-namespace network topologies that REQUIRE
the virtual network (br0/br1 bridges + ns_ecu1/ns_ecu2/ns_ecu3 namespaces).
They are skipped on Windows and on Linux without VNet/sudo.

Topologies:
  A: Multi-homed provider (ns_ecu1 dual-NIC → ns_ecu3 client)
  B: Split-interface requirements (provider per-iface → single client)
  C: Multi-instance same interface (two instances on ns_ecu1)
  D: Multi-instance different interfaces (ns_ecu1 + ns_ecu2 → ns_ecu3 client)
  E: Static config / No SD (direct endpoint addressing)
  F: Shared endpoint (two services on same port)
"""
import os
import sys
import json
import time
import subprocess
import socket
import datetime
import threading
import unittest
import pytest
import tempfile
import socket
import datetime
import threading
from tools.fusion.environment import NetworkEnvironment
from tools.fusion.integration import IntegrationTestContext
from tools.fusion.config_gen import ConfigGenerator
from tools.fusion.utils import to_wsl, get_ns_iface

# Skip entire module if not on Linux
if sys.platform != "linux":
    raise unittest.SkipTest("Config use-case tests require Linux (VNet namespaces)")

# Global environment — detect once
ENV = NetworkEnvironment()

def _ensure_vnet():
    """Detect environment and enforce VNet availability."""
    if not ENV.interfaces:
        ENV.detect()
    if not ENV.has_vnet:
        pytest.skip("VNet not available (requires br0/namespaces with sudo)")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
JS_APP_DIR = os.path.join(PROJECT_ROOT, "examples", "integrated_apps", "js_app")

# Standard SD multicast address used across all VNet use cases
SD_MCAST = {"ip": "224.224.224.245", "port": 30490, "proto": "udp"}


class TestUseCases:
    """
    VNet-isolated configuration use-case tests.
    Each test creates its own IntegrationTestContext with a custom topology.
    """
    pytestmark = [pytest.mark.needs_netns]
    
    def setup_method(self):
        """Ensure VNet is available before each test."""
        _ensure_vnet()

    def test_a_multi_homed_provider(self):
        """
        Scenario A: Multi-Homed Provider
        Provider offers Service 0x1001 on veth0 (br0) and veth1 (br1).
        JS Client on ns_ecu3 finds it via br0.
        """
        with IntegrationTestContext("test_a_multi_homed_provider") as ctx:
            if1 = get_ns_iface(ENV, "ns_ecu1", "10.0.1.1")
            if2 = get_ns_iface(ENV, "ns_ecu1", "10.0.2.1")
            if3 = get_ns_iface(ENV, "ns_ecu3", "10.0.1.3")

            ctx.config_gen.add_interface("primary", if1, {
                "sd_mcast": SD_MCAST,
                "svc_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
                "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("secondary", if2, {
                "sd_mcast": SD_MCAST,
                "svc_ep_2": {"ip": "10.0.2.1", "port": 31002, "proto": "udp"},
                "sd_uc": {"ip": "10.0.2.1", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("client_iface", if3, {
                 "sd_mcast": SD_MCAST,
                 "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"})

            ctx.config_gen.add_instance("multi_provider", 
                unicast_bind={"primary": "sd_uc", "secondary": "sd_uc"},
                providing={
                    "MathService": {
                        "service_id": 0x1001,
                        "instance_id": 1,
                        "major_version": 1,
                        "offer_on": {"primary": "svc_ep", "secondary": "svc_ep_2"}
                    }
                },
                interfaces=["primary", "secondary"]
            ).add_instance("js_client",
                 unicast_bind={"client_iface": "client_ep"},
                 required={"MathService": {"service_id": 0x1001, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]}},
                 interfaces=["client_iface"]
            )

            config_path = ctx.config_gen.save(os.path.join(ctx.log_dir, "config.json"))
            wsl_config_path = to_wsl(config_path)

            # Python Provider
            provider_code = f"""
import sys, time, os
sys.path.append(r'{to_wsl(PROJECT_ROOT)}')
sys.path.append(r'{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
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

rt = SomeIpRuntime(r'{wsl_config_path}', 'multi_provider')
rt.offer_service('MathService', Handler())
rt.start()
print("PROVIDER_STARTED")
sys.stdout.flush()
while True: time.sleep(1)
            """
            prov_runner = ctx.run_python_code(provider_code, "provider", ns="ns_ecu1")
            assert prov_runner.wait_for_output("PROVIDER_STARTED", timeout=10), "Provider failed to start"
            
            # JS Client
            js_code = """
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
            client_runner = ctx.run_js_code(js_code, wsl_config_path, 'js_client', JS_APP_DIR, ns="ns_ecu3")
            
            assert client_runner.wait_for_output("JS_RESULT: 30", timeout=40), "JS Client failed or timed out"


    def test_b_complex_requirements(self):
        """
        Scenario B: Complex Requirements (Split Interfaces)
        Instance requires ServiceA on iface1 and ServiceB on iface2.
        """
        with IntegrationTestContext("test_b_complex_requirements") as ctx:
            if1 = get_ns_iface(ENV, "ns_ecu1", "10.0.1.1")
            if2 = get_ns_iface(ENV, "ns_ecu2", "10.0.1.2")
            if3 = get_ns_iface(ENV, "ns_ecu3", "10.0.1.3")

            ctx.config_gen.add_interface("primary", if1, {
                "sd_mcast": SD_MCAST,
                "svc_a_ep": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
                "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("secondary", if2, {
                "sd_mcast": SD_MCAST,
                "svc_b_ep": {"ip": "10.0.1.2", "port": 31002, "proto": "udp"},
                "sd_uc": {"ip": "10.0.1.2", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("client_iface", if3, {
                 "sd_mcast": SD_MCAST,
                 "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"})

            ctx.config_gen.add_instance("provider_a", unicast_bind={"primary": "sd_uc"},
                providing={"ServiceA": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "svc_a_ep"}}},
                interfaces=["primary"]
            ).add_instance("provider_b", unicast_bind={"secondary": "sd_uc"},
                providing={"ServiceB": {"service_id": 0x2000, "instance_id": 1, "major_version": 1, "offer_on": {"secondary": "svc_b_ep"}}},
                interfaces=["secondary"]
            ).add_instance("split_client", unicast_bind={"client_iface": "client_ep"},
                required={
                    "ServiceA": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]},
                    "ServiceB": {"service_id": 0x2000, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]}
                },
                interfaces=["client_iface"]
            )
            
            config_path = ctx.config_gen.save(os.path.join(ctx.log_dir, "config.json"))
            wsl_config_path = to_wsl(config_path)

            common_script = f"""
import sys, time, os
sys.path.append(r'{to_wsl(PROJECT_ROOT)}')
sys.path.append(r'{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
class MockHandler(RequestHandler):
    def __init__(self, sid): self.sid = sid
    def get_service_id(self): return self.sid
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, b'')
"""
            p_a = ctx.run_python_code(common_script + f"\nrt=SomeIpRuntime('{wsl_config_path}', 'provider_a')\nrt.offer_service('ServiceA', MockHandler(0x1000))\nrt.start()\nprint('PROV_A_READY')\nsys.stdout.flush()\nwhile True: time.sleep(1)", 
                                                   "provider_a", ns="ns_ecu1")
            p_b = ctx.run_python_code(common_script + f"\nrt=SomeIpRuntime('{wsl_config_path}', 'provider_b')\nrt.offer_service('ServiceB', MockHandler(0x2000))\nrt.start()\nprint('PROV_B_READY')\nsys.stdout.flush()\nwhile True: time.sleep(1)",
                                                   "provider_b", ns="ns_ecu2")
            
            assert p_a.wait_for_output("PROV_A_READY", timeout=10)
            assert p_b.wait_for_output("PROV_B_READY", timeout=10)

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
            p_c = ctx.run_python_code(client_script, "client", ns="ns_ecu3")
            assert p_c.wait_for_output("FOUND_BOTH", timeout=30), "Client failed to find services"


    def test_c_multi_instance_same_iface(self):
        """
        Scenario C: Multiple Instances (Same Interface)
        Two instances of Service 0x1000 on ns_ecu1 with different Instance IDs.
        """
        with IntegrationTestContext("test_c_multi_instance") as ctx:
            if1 = get_ns_iface(ENV, "ns_ecu1", "10.0.1.1")
            if3 = get_ns_iface(ENV, "ns_ecu3", "10.0.1.3")

            ctx.config_gen.add_interface("primary", if1, {
                "sd_mcast": SD_MCAST,
                "svc_ep_1": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
                "svc_ep_2": {"ip": "10.0.1.1", "port": 31002, "proto": "udp"},
                "sd_uc_1": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"},
                "sd_uc_2": {"ip": "10.0.1.1", "port": 31005, "proto": "udp"} 
            }, sd={"endpoint": "sd_mcast"}).add_interface("client_iface", if3, {
                 "sd_mcast": SD_MCAST,
                 "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"})
            
            ctx.config_gen.add_instance("inst_1", unicast_bind={"primary": "sd_uc_1"},
                providing={"Svc": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "svc_ep_1"}}}, interfaces=["primary"]
            ).add_instance("inst_2", unicast_bind={"primary": "sd_uc_2"},
                providing={"Svc": {"service_id": 0x1000, "instance_id": 2, "major_version": 1, "offer_on": {"primary": "svc_ep_2"}}}, interfaces=["primary"]
            ).add_instance("client", unicast_bind={"client_iface": "client_ep"},
                required={
                    "Svc1": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]},
                    "Svc2": {"service_id": 0x1000, "instance_id": 2, "major_version": 1, "find_on": ["client_iface"]}
                }, interfaces=["client_iface"])

            config_path = ctx.config_gen.save(os.path.join(ctx.log_dir, "config.json"))
            wsl_config_path = to_wsl(config_path)
            
            common = f"""
import sys, time, os
sys.path.append(r'{to_wsl(PROJECT_ROOT)}')
sys.path.append(r'{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
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
            p1 = ctx.run_python_code(prov_script, "inst1", ns="ns_ecu1")
            
            prov2_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'inst_2')
rt.offer_service('Svc', Handler())
rt.start()
print('INST_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
            p2 = ctx.run_python_code(prov2_script, "inst2", ns="ns_ecu1")
                             
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
            pc = ctx.run_python_code(client_script, "client", ns="ns_ecu3")
            assert pc.wait_for_output("FOUND_BOTH", timeout=30), "Client failed to find both instances"


    def test_d_multi_instance_diff_iface(self):
        """
        Scenario D: Multiple Instances (Different Interfaces)
        Instance 1 on ns_ecu1, Instance 2 on ns_ecu2.
        Client on ns_ecu3 finds both and verifies source IPs.
        """
        with IntegrationTestContext("test_d_multi_instance") as ctx:
            if1 = get_ns_iface(ENV, "ns_ecu1", "10.0.1.1")
            if2 = get_ns_iface(ENV, "ns_ecu2", "10.0.1.2")
            if3 = get_ns_iface(ENV, "ns_ecu3", "10.0.1.3")

            ctx.config_gen.add_interface("primary", if1, {
                "sd_mcast": SD_MCAST,
                "svc_ep_1": {"ip": "10.0.1.1", "port": 31001, "proto": "udp"},
                "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("secondary", if2, {
                "sd_mcast": SD_MCAST,
                "svc_ep_2": {"ip": "10.0.1.2", "port": 31002, "proto": "udp"},
                "sd_uc": {"ip": "10.0.1.2", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("client_iface", if3, {
                 "sd_mcast": SD_MCAST,
                 "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"})

            ctx.config_gen.add_instance("inst_1", unicast_bind={"primary": "sd_uc"},
                providing={"Svc": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "svc_ep_1"}}},
                interfaces=["primary"]
            ).add_instance("inst_2", unicast_bind={"secondary": "sd_uc"},
                providing={"Svc": {"service_id": 0x1000, "instance_id": 2, "major_version": 1, "offer_on": {"secondary": "svc_ep_2"}}},
                interfaces=["secondary"]
            ).add_instance("client", unicast_bind={"client_iface": "client_ep"},
                required={
                    "Svc1": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]},
                    "Svc2": {"service_id": 0x1000, "instance_id": 2, "major_version": 1, "find_on": ["client_iface"]}
                },
                interfaces=["client_iface"]
            )
            
            config_path = ctx.config_gen.save(os.path.join(ctx.log_dir, "config.json"))
            wsl_config_path = to_wsl(config_path)

            common = f"""
import sys, time, os
sys.path.append(r'{to_wsl(PROJECT_ROOT)}')
sys.path.append(r'{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
class Handler(RequestHandler):
    def get_service_id(self): return 0x1000
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, b'')
"""
            # Instance 1 (Python on ns_ecu1)
            p1 = ctx.run_python_code(common + f"rt = SomeIpRuntime('{wsl_config_path}', 'inst_1')\nrt.offer_service('Svc', Handler())\nrt.start()\nprint('INST_1_READY')\nsys.stdout.flush()\nwhile True: time.sleep(1)", "inst1", ns="ns_ecu1")
             
            # Instance 2 (Python on ns_ecu2)
            p2 = ctx.run_python_code(common + f"rt = SomeIpRuntime('{wsl_config_path}', 'inst_2')\nrt.offer_service('Svc', Handler())\nrt.start()\nprint('INST_2_READY')\nsys.stdout.flush()\nwhile True: time.sleep(1)", "inst2", ns="ns_ecu2")

            assert p1.wait_for_output("INST_1_READY", timeout=10)
            assert p2.wait_for_output("INST_2_READY", timeout=10)

            client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
s1 = rt.get_client('Svc1', None, timeout=2.0)
s2 = rt.get_client('Svc2', None, timeout=2.0)
if s1 and s2:
    print(f"FOUND: BOTH")
rt.stop()
"""
            c_proc = ctx.run_python_code(client_script, "client", ns="ns_ecu3")
            assert c_proc.wait_for_output("FOUND: BOTH", timeout=30), "Client failed to verify both instances."


    def test_e_static_config(self):
        """
        Scenario E: Static Configuration (No SD)
        Direct endpoint addressing without Service Discovery.
        Tests explicit port binding (non-ephemeral).
        """
        with IntegrationTestContext("test_e_static_config") as ctx:
            if1 = get_ns_iface(ENV, "ns_ecu1", "10.0.1.1")
            if2 = get_ns_iface(ENV, "ns_ecu2", "10.0.1.2")

            ctx.config_gen.add_interface("primary", if1, {
                "svc_ep": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
            }).add_interface("secondary", if2, {
                 "client_ep": {"ip": "10.0.1.2", "port": 32000, "proto": "udp"}
            })
            ctx.config_gen.add_instance("static_server", unicast_bind={"primary": "svc_ep"},
                providing={"Svc": {"service_id": 0x9999, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "svc_ep"}}})
            ctx.config_gen.add_instance("static_client", unicast_bind={"secondary": "client_ep"},
                required={"Svc": {"service_id": 0x9999, "instance_id": 1, "major_version": 1, "find_on": ["secondary"]}})
            
            config_path = ctx.config_gen.save(os.path.join(ctx.log_dir, "config.json"))
            wsl_config_path = to_wsl(config_path)

            common = f"""
import sys, time, os
sys.path.append(r'{to_wsl(PROJECT_ROOT)}')
sys.path.append(r'{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
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
            srv = ctx.run_python_code(srv_script, "server", ns="ns_ecu1")
            assert srv.wait_for_output("SERVER_READY", timeout=10)

            client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'static_client')
rt.start()
time.sleep(1)
rt.send_request(0x9999, 1, b'', ('10.0.1.1', 31000, 'udp'))
time.sleep(1)
rt.stop()
"""
            ctx.run_python_code(client_script, "client", ns="ns_ecu2")
            
            assert srv.wait_for_output("RECEIVED_REQ", timeout=10)


    def test_f_shared_endpoint(self):
        """
        Scenario F: Shared Endpoint
        Two services on the same IP:port — runtime dispatcher routes by service_id.
        """
        with IntegrationTestContext("test_f_shared_endpoint") as ctx:
            if1 = get_ns_iface(ENV, "ns_ecu1", "10.0.1.1")
            if3 = get_ns_iface(ENV, "ns_ecu3", "10.0.1.3")

            ctx.config_gen.add_interface("primary", if1, {
                "sd_mcast": SD_MCAST,
                "shared_ep": {"ip": "10.0.1.1", "port": 31050, "proto": "udp"},
                "sd_uc": {"ip": "10.0.1.1", "port": 31000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"}).add_interface("client_iface", if3, {
                 "sd_mcast": SD_MCAST,
                 "client_ep": {"ip": "10.0.1.3", "port": 32000, "proto": "udp"}
            }, sd={"endpoint": "sd_mcast"})

            ctx.config_gen.add_instance("shared_server", unicast_bind={"primary": "sd_uc"},
                providing={
                    "SvcA": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "shared_ep"}},
                    "SvcB": {"service_id": 0x2000, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "shared_ep"}}
                }, interfaces=["primary"]
            ).add_instance("client", unicast_bind={"client_iface": "client_ep"},
                required={
                    "SvcA": {"service_id": 0x1000, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]},
                    "SvcB": {"service_id": 0x2000, "instance_id": 1, "major_version": 1, "find_on": ["client_iface"]}
                }, interfaces=["client_iface"])
            
            config_path = ctx.config_gen.save(os.path.join(ctx.log_dir, "config.json"))
            wsl_config_path = to_wsl(config_path)

            common = f"""
import sys, time, os
sys.path.append(r'{to_wsl(PROJECT_ROOT)}')
sys.path.append(r'{to_wsl(os.path.join(PROJECT_ROOT, 'src', 'python'))}')
from fusion_hawking.runtime import SomeIpRuntime, RequestHandler, ReturnCode
"""
            srv_script = common + f"""
class Handler(RequestHandler):
    def __init__(self, sid): self.sid = sid
    def get_service_id(self): return self.sid
    def get_major_version(self): return 1
    def get_minor_version(self): return 0
    def handle(self, h, p): return (ReturnCode.E_OK, p)

rt = SomeIpRuntime('{wsl_config_path}', 'shared_server')
rt.offer_service('SvcA', Handler(0x1000))
rt.offer_service('SvcB', Handler(0x2000))
rt.start()
print('SRV_READY')
sys.stdout.flush()
while True: time.sleep(1)
"""
            srv = ctx.run_python_code(srv_script, "server", ns="ns_ecu1")
            assert srv.wait_for_output("SRV_READY", timeout=10)

            client_script = common + f"""
rt = SomeIpRuntime('{wsl_config_path}', 'client')
rt.start()
time.sleep(2)
success = rt.get_client('SvcA', None, timeout=2.0) and rt.get_client('SvcB', None, timeout=2.0)
print('OK' if success else 'FAIL')
rt.stop()
"""
            pc = ctx.run_python_code(client_script, "client", ns="ns_ecu3")
            assert pc.wait_for_output("OK", timeout=30)
