import unittest
import sys
import os
import struct
import socket

# Add build/generated/python and src/python to path
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))

from runtime import SomeIpRuntime, MathServiceStub, MathServiceClient
from fusion_hawking.runtime import MessageType, ReturnCode, SessionIdManager


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
        # Directly set counter to near wrap point
        # After returning 0xFFFF, next value = (0xFFFF % 0xFFFF) + 1 = 1
        self.manager._counters[(0x1000, 0x0001)] = 0xFFFF
        sid1 = self.manager.next_session_id(0x1000, 0x0001)
        sid2 = self.manager.next_session_id(0x1000, 0x0001)
        self.assertEqual(sid1, 0xFFFF)
        # Wraps to 1 (not 0, as 0 is invalid per SOME/IP)
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
        # Use relative path to test config
        config_path = os.path.join(os.getcwd(), 'tests', 'test_config.json')
        self.runtime = SomeIpRuntime(config_path, "test_instance")
        self.runtime.start()

    def tearDown(self):
        self.runtime.stop()

    def test_offer_service(self):
        stub = MathServiceStub()
        self.runtime.offer_service("math-service", stub)
        self.assertIn(stub.SERVICE_ID, self.runtime.services)
        
    def test_get_client(self):
        # Inject service discovery
        # Key is now (sid, major_version)
        self.runtime.remote_services[(4097, 0)] = ('127.0.0.1', 12345, 'udp')
        
        # MathServiceClient has SERVICE_ID=4097. Runtime defaults major_ver to 1 if not in config.
        # But wait, `get_client` takes `service_name`.
        # Config for "math-client": "service_id": 4097. Major version not specified, defaults to 1?
        # Let's check `runtime.py` get_client impl.
        # "major_version = req_cfg.get('major_version', 1)"
        # So it looks for (4097, 1).
        # But `MathServiceStub` default major version is 1?
        # Let's check `MathServiceClient`. If generated, it has MAJOR_VERSION.
        # In this test, we import `MathServiceClient` from `runtime`.
        # Wait, `from runtime import ... MathServiceClient`.
        # This `runtime` is likely `tests/runtime.py`? No, `sys.path` inserts `src/python` and `build/generated/python`.
        # If `MathServiceClient` is from generated code, it has headers.
        
        # Let's align with default lookups.
        self.runtime.remote_services[(4097, 1)] = ('127.0.0.1', 12345, 'udp')
        
        client = self.runtime.get_client("math-client", MathServiceClient)
        # If config is missing or "math-client" not in required, it returns None.
        # `tests/test_config.json` needs to be checked.
        if client is None:
             # Fallback for test robustness if config is missing key
             # Mock config?
             pass
             
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
    """Tests for ephemeral port (port 0) resolution in the Python runtime.
    
    When a service endpoint is configured with port 0, the OS assigns an
    ephemeral port upon binding. The runtime must use the actual bound port
    in SD offers, not the configured value of 0.
    """
    
    def test_udp_ephemeral_port_resolved(self):
        """Verify that UDP endpoints configured with port 0 get a real port after binding."""
        import json, tempfile
        config = {
            "interfaces": {
                "primary": {
                    "name": "lo",
                    "endpoints": {
                        "main_udp": {"ip": "127.0.0.1", "port": 0, "version": 4, "protocol": "udp"},
                        "sd_mcast": {"ip": "224.224.224.245", "port": 30490, "version": 4, "protocol": "udp"}
                    },
                    "sd": {"endpoint": "sd_mcast"}
                }
            },
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
                actual = sock.getsockname()[1]
                self.assertGreater(actual, 0, f"Port must be > 0 after binding, got {actual}")
                self.assertEqual(port, actual, "Listener key port must match actual bound port")
            
            # Check offered_services entries have non-zero port
            for entry in rt.offered_services:
                sid, iid, maj, mnr, ip, port, proto, alias = entry
                self.assertGreater(port, 0, f"Offered service port must be > 0 for SID {sid}, got {port}")
            
            rt.stop()
        finally:
            os.unlink(cfg_path)

    def test_tcp_ephemeral_port_resolved(self):
        """Verify that TCP endpoints configured with port 0 get a real port after binding."""
        import json, tempfile
        config = {
            "interfaces": {
                "primary": {
                    "name": "lo",
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
            os.unlink(cfg_path)


if __name__ == '__main__':
    unittest.main()
