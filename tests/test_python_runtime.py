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
        self.assertEqual(ReturnCode.OK, 0x00)
        
    def test_not_ok_value(self):
        self.assertEqual(ReturnCode.NOT_OK, 0x01)
        
    def test_unknown_service_value(self):
        self.assertEqual(ReturnCode.UNKNOWN_SERVICE, 0x02)
        
    def test_unknown_method_value(self):
        self.assertEqual(ReturnCode.UNKNOWN_METHOD, 0x03)
        
    def test_timeout_value(self):
        self.assertEqual(ReturnCode.TIMEOUT, 0x06)
        
    def test_malformed_message_value(self):
        self.assertEqual(ReturnCode.MALFORMED_MESSAGE, 0x09)
        
    def test_e2e_values(self):
        self.assertEqual(ReturnCode.E2E_REPEATED, 0x0B)
        self.assertEqual(ReturnCode.E2E_WRONG_SEQUENCE, 0x0C)
        self.assertEqual(ReturnCode.E2E_NOT_AVAILABLE, 0x0D)
        self.assertEqual(ReturnCode.E2E_NO_NEW_DATA, 0x0E)


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
        self.assertIsNotNone(self.runtime.sock)
        
    def test_runtime_has_services_dict(self):
        self.assertIsInstance(self.runtime.services, dict)
        
    def test_runtime_has_remote_services_dict(self):
        self.assertIsInstance(self.runtime.remote_services, dict)


if __name__ == '__main__':
    unittest.main()
