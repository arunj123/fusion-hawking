import unittest
import sys
import os
import struct
import socket
import json
import shutil

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

# Add build/generated/python and src/python to path
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src', 'python'))

from tools.fusion.utils import _get_env as get_environment
from runtime import SomeIpRuntime, MathServiceStub, MathServiceClient
from fusion_hawking.runtime import MessageType, ReturnCode, SessionIdManager

def generate_config(env, output_dir):
    """Generate configuration for Python Runtime Unit Tests"""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "runtime_test_config.json")
    
    # Use loopback for unit tests for stability and speed
    ipv4 = "127.0.0.1" 
    iface_name = "Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo"
    
    config = {
        "interfaces": {
            "primary": {
                "name": iface_name,
                "endpoints": {
                    "test_ep": {
                        "ip": ipv4,
                        "port": 0,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "sd_multicast": {
                        "ip": "224.0.0.3",
                        "port": 30890,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "sd_bind_ep": {
                        "ip": ipv4,
                        "port": 0,
                        "version": 4,
                        "protocol": "udp"
                    }
                },
                "sd": {
                    "endpoint": "sd_multicast"
                }
            }
        },
        "instances": {
            "test_instance": {
                "unicast_bind": {
                    "primary": "sd_bind_ep"
                },
                "providing": {
                    "math-service": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "offer_on": {
                            "primary": "test_ep"
                        }
                    }
                },
                "required": {
                    "math-client": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "find_on": [
                            "primary"
                        ]
                    }
                },
                "sd": {
                    "cycle_offer_ms": 100
                }
            },
            "python_test_client": {
                "unicast_bind": {
                    "primary": "sd_bind_ep"
                },
                "required": {
                    "sort-service": {
                        "service_id": 12289,
                        "instance_id": 1,
                        "find_on": [
                            "primary"
                        ]
                    }
                },
                "sd": {
                    "cycle_offer_ms": 1000
                }
            }
        }
    }
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        
    return config_path


class TestMessageType(unittest.TestCase):
    """Tests for SOME/IP MessageType enum."""
    
    def test_request_value(self):
        self.assertEqual(MessageType.REQUEST, 0x00)
        
    def test_request_no_return_value(self):
        self.assertEqual(MessageType.REQUEST_NO_RETURN, 0x01)
        
    def test_notification_value(self):
        self.assertEqual(MessageType.NOTIFICATION, 0x02)
        
    def test_response_value(self):
        self.assertEqual(MessageType.RESPONSE, 0x80)
        
    def test_error_value(self):
        self.assertEqual(MessageType.ERROR, 0x81)
        
    def test_tp_variants(self):
        self.assertEqual(MessageType.REQUEST_WITH_TP, 0x20)
        self.assertEqual(MessageType.REQUEST_NO_RETURN_WITH_TP, 0x21)
        self.assertEqual(MessageType.NOTIFICATION_WITH_TP, 0x22)
        self.assertEqual(MessageType.RESPONSE_WITH_TP, 0xA0)
        self.assertEqual(MessageType.ERROR_WITH_TP, 0xA1)


class TestReturnCode(unittest.TestCase):
    """Tests for SOME/IP ReturnCode enum."""
    
    def test_ok_value(self):
        self.assertEqual(ReturnCode.E_OK, 0x00)
        
    def test_not_ok_value(self):
        self.assertEqual(ReturnCode.E_NOT_OK, 0x01)
        
    def test_unknown_service_value(self):
        self.assertEqual(ReturnCode.E_UNKNOWN_SERVICE, 0x02)
        
    def test_unknown_method_value(self):
        self.assertEqual(ReturnCode.E_UNKNOWN_METHOD, 0x03)
        
    def test_timeout_value(self):
        self.assertEqual(ReturnCode.E_TIMEOUT, 0x06)
        
    def test_malformed_message_value(self):
        self.assertEqual(ReturnCode.E_MALFORMED_MESSAGE, 0x09)
        
    def test_e2e_values(self):
        self.assertEqual(ReturnCode.E_E2E_REPEATED, 0x0B)
        self.assertEqual(ReturnCode.E_E2E_WRONG_SEQUENCE, 0x0C)
        self.assertEqual(ReturnCode.E_E2E_NOT_AVAILABLE, 0x0D)
        self.assertEqual(ReturnCode.E_E2E_NO_NEW_DATA, 0x0E)


class TestSessionIdManager(unittest.TestCase):
    """Tests for SessionIdManager class."""
    
    def setUp(self):
        self.manager = SessionIdManager()
        
    def test_initial_session_id_is_one(self):
        sid = self.manager.next_session_id(0x1000, 0x0001)
        self.assertEqual(sid, 1)
        
    def test_session_id_increments(self):
        sid1 = self.manager.next_session_id(0x1000, 0x0001)
        sid2 = self.manager.next_session_id(0x1000, 0x0001)
        sid3 = self.manager.next_session_id(0x1000, 0x0001)
        self.assertEqual(sid1, 1)
        self.assertEqual(sid2, 2)
        self.assertEqual(sid3, 3)
        
    def test_different_services_have_independent_ids(self):
        sid1 = self.manager.next_session_id(0x1000, 0x0001)
        sid2 = self.manager.next_session_id(0x2000, 0x0001)
        sid3 = self.manager.next_session_id(0x1000, 0x0001)
        self.assertEqual(sid1, 1)
        self.assertEqual(sid2, 1)  # Different service, starts at 1
        self.assertEqual(sid3, 2)
        
    def test_different_methods_have_independent_ids(self):
        sid1 = self.manager.next_session_id(0x1000, 0x0001)
        sid2 = self.manager.next_session_id(0x1000, 0x0002)
        self.assertEqual(sid1, 1)
        self.assertEqual(sid2, 1)  # Different method, starts at 1
        
    def test_reset_single_counter(self):
        self.manager.next_session_id(0x1000, 0x0001)
        self.manager.next_session_id(0x1000, 0x0001)
        self.manager.reset(0x1000, 0x0001)
        sid = self.manager.next_session_id(0x1000, 0x0001)
        self.assertEqual(sid, 1)  # Reset back to 1
        
    def test_reset_all_counters(self):
        self.manager.next_session_id(0x1000, 0x0001)
        self.manager.next_session_id(0x2000, 0x0001)
        self.manager.reset_all()
        sid1 = self.manager.next_session_id(0x1000, 0x0001)
        sid2 = self.manager.next_session_id(0x2000, 0x0001)
        self.assertEqual(sid1, 1)
        self.assertEqual(sid2, 1)
        
    def test_session_id_wraps_at_65535(self):
        self.manager._counters[(0x1000, 0x0001)] = 0xFFFF
        sid1 = self.manager.next_session_id(0x1000, 0x0001)
        sid2 = self.manager.next_session_id(0x1000, 0x0001)
        self.assertEqual(sid1, 0xFFFF)
        self.assertEqual(sid2, 1)


class MockSocket:
    def __init__(self):
        self.sent = []
        self.bound_port = 0
    
    def bind(self, addr):
        self.bound_port = addr[1]
        
    def getsockname(self):
        return ('0.0.0.0', self.bound_port)
        
    def sendto(self, data, addr):
        self.sent.append((data, addr))
        
    def setsockopt(self, *args): pass
    def setblocking(self, *args): pass


class TestPythonRuntime(unittest.TestCase):
    def setUp(self):
        env = get_environment()
        
        # Use FUSION_LOG_DIR if set, otherwise temp/local
        log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "unit_test_runtime"))
        os.makedirs(log_dir, exist_ok=True)
        
        self.config_path = generate_config(env, log_dir)
        self.runtime = SomeIpRuntime(self.config_path, "test_instance")
        self.runtime.start()

    def tearDown(self):
        if self.runtime:
             self.runtime.stop()
        # Clean up config if desired, or keep for debugging
        # os.remove(self.config_path)

    def test_offer_service(self):
        stub = MathServiceStub()
        self.runtime.offer_service("math-service", stub)
        self.assertIn(stub.SERVICE_ID, self.runtime.services)
        
    def test_get_client(self):
        # Inject service discovery
        self.runtime.remote_services[(4097, 1)] = ('127.0.0.1', 12345, 'udp')
        
        client = self.runtime.get_client("math-client", MathServiceClient)
        # Assuming MathServiceClient is available and importable
        if client:
             self.assertIsInstance(client, MathServiceClient)
             self.assertEqual(client.runtime, self.runtime)
        
    def test_runtime_has_logger(self):
        self.assertIsNotNone(self.runtime.logger)
        
    def test_runtime_has_socket(self):
        self.assertTrue(self.runtime.listeners or self.runtime.sd_listeners)
        
    def test_runtime_has_services_dict(self):
        self.assertIsInstance(self.runtime.services, dict)
        
    def test_runtime_has_remote_services_dict(self):
        self.assertIsInstance(self.runtime.remote_services, dict)


class TestEphemeralPortTracking(unittest.TestCase):
    """Tests for ephemeral port (port 0) resolution in the Python runtime."""
    
    def test_udp_ephemeral_port_resolved(self):
        """Verify that UDP endpoints configured with port 0 get a real port after binding."""
        import json, tempfile
        config = {
            "interfaces": {
                "primary": {
                    "name": "lo" if os.name != 'nt' else "Loopback Pseudo-Interface 1",
                    "endpoints": {
                        "main_udp": {"ip": "127.0.0.1", "port": 0, "version": 4, "protocol": "udp"},
                        "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "version": 4, "protocol": "udp"}
                    },
                    "sd": {"endpoint": "sd_mcast"}
                }
            },
            # Flat endpoints for legacy compat if runtime still checks them? 
            # Ideally runtime only checks interfaces->endpoints now but keeping for safety
            "endpoints": {
                "main_udp": {"ip": "127.0.0.1", "port": 0, "version": 4, "protocol": "udp"},
                "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "version": 4, "protocol": "udp"}
            },
            "instances": {
                "test_ephemeral": {
                    "interfaces": ["primary"],
                    "providing": {
                        "test_svc": {
                            "service_id": 9999,
                            "instance_id": 1,
                            "endpoint": "main_udp",
                            "major_version": 1,
                            "minor_version": 0
                        }
                    },
                    "sd": {"multicast_endpoint": "sd_mcast"}
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            f.flush()
            cfg_path = f.name
        try:
            rt = SomeIpRuntime(cfg_path, "test_ephemeral")
            rt.start()
            # Check that listeners were bound to a real port (not 0)
            for (ip, port, proto), sock in rt.listeners.items():
                if proto == 'udp': # Ensure we check UDP
                     actual = sock.getsockname()[1]
                     self.assertGreater(actual, 0, f"Port must be > 0 after binding, got {actual}")
                     # In some implementations, the key might still be the config port (0) if not updated.
                     # But `listeners` usually keyed by bound addr.
                     # If keyed by config, we iterate values.
            
            # Check offered_services entries have non-zero port
            for entry in rt.offered_services:
                sid, iid, maj, mnr, ip, port, proto, alias = entry
                self.assertGreater(port, 0, f"Offered service port must be > 0 for SID {sid}, got {port}")
            
            rt.stop()
        finally:
            try:
                os.unlink(cfg_path)
            except: pass

    def test_tcp_ephemeral_port_resolved(self):
        """Verify that TCP endpoints configured with port 0 get a real port after binding."""
        import json, tempfile
        config = {
            "interfaces": {
                "primary": {
                    "name": "lo" if os.name != 'nt' else "Loopback Pseudo-Interface 1",
                    "endpoints": {
                        "main_tcp": {"ip": "127.0.0.1", "port": 0, "version": 4, "protocol": "tcp"},
                        "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "version": 4, "protocol": "udp"}
                    },
                    "sd": {"endpoint": "sd_mcast"}
                }
            },
            "endpoints": {
                "main_tcp": {"ip": "127.0.0.1", "port": 0, "version": 4, "protocol": "tcp"},
                "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "version": 4, "protocol": "udp"}
            },
            "instances": {
                "test_tcp_eph": {
                    "interfaces": ["primary"],
                    "providing": {
                        "tcp_svc": {
                            "service_id": 9998,
                            "instance_id": 1,
                            "endpoint": "main_tcp",
                            "major_version": 1,
                            "minor_version": 0
                        }
                    },
                    "sd": {"multicast_endpoint": "sd_mcast"}
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            f.flush()
            cfg_path = f.name
        try:
            rt = SomeIpRuntime(cfg_path, "test_tcp_eph")
            rt.start()
            # Check TCP listeners were bound to a real port
            for (ip, port, proto), sock in rt.listeners.items():
                if proto == 'tcp':
                    actual = sock.getsockname()[1]
                    self.assertGreater(actual, 0, f"TCP port must be > 0, got {actual}")
            rt.stop()
        finally:
            try:
                os.unlink(cfg_path)
            except: pass


if __name__ == '__main__':
    unittest.main()
