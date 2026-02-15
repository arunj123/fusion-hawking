import unittest
import struct
import socket
import json
import os
from unittest.mock import MagicMock, patch
from tools.fusion.utils import _get_env as get_environment
from fusion_hawking.runtime import SessionIdManager, SomeIpRuntime, MessageType

def generate_config(env, output_dir):
    """Generate configuration for Python Coverage Unit Tests"""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "coverage_test_config.json")
    
    # Use loopback for unit tests
    ipv4 = "127.0.0.1" 
    iface_name = "Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo"
    
    config = {
        "interfaces": {
            "primary": {
                "name": iface_name,
                "endpoints": {
                    "sd_multicast": {
                        "ip": "224.0.0.3",
                        "port": 30890,
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
                "unicast_bind": {},
                "providing": {},
                "required": {},
                "sd": {}
            }
        }
    }
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        
    return config_path

class TestSessionIdManager(unittest.TestCase):
    def test_increment_and_wrap(self):
        mgr = SessionIdManager()
        # Test initial
        self.assertEqual(mgr.next_session_id(1, 1), 1)
        self.assertEqual(mgr.next_session_id(1, 1), 2)
        
        # Test independent counters
        self.assertEqual(mgr.next_session_id(2, 2), 1)
        self.assertEqual(mgr.next_session_id(1, 1), 3)
        
        # Test Wrap
        mgr._counters[(1, 1)] = 0xFFFF
        self.assertEqual(mgr.next_session_id(1, 1), 0xFFFF) # Returns current (max)
        self.assertEqual(mgr.next_session_id(1, 1), 1)      # Next wraps to 1
        
    def test_reset(self):
        mgr = SessionIdManager()
        mgr.next_session_id(1, 1)
        mgr.next_session_id(1, 1)
        mgr.reset(1, 1)
        self.assertEqual(mgr.next_session_id(1, 1), 1) # Back to 1 (conceptually reset sets counter to 1 or 0? impl sets to 1 in dict, next returns current. Wait. impl: if not in dict: set to 1. return current. increment. So reset should remove from dict or set to 1. Impl: `_counters[...] = 1`. Next call: returns 1, sets to 2. Correct.
        
    def test_reset_all(self):
        mgr = SessionIdManager()
        mgr.next_session_id(1, 1)
        mgr.next_session_id(2, 2)
        mgr.reset_all()
        self.assertEqual(len(mgr._counters), 0)

class TestRuntimeDetailed(unittest.TestCase):
    def setUp(self):
        env = get_environment()
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        log_dir = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "unit_test_coverage"))
        os.makedirs(log_dir, exist_ok=True)
        
        self.config_path = generate_config(env, log_dir)
        self.runtime = SomeIpRuntime(self.config_path, "test_instance")
        self.runtime.logger = MagicMock()
        # Mock sockets to prevent network activity
        # Close actual sockets created by init before mocking to avoid ResourceWarning
        if hasattr(self.runtime, 'sock') and self.runtime.sock:
            self.runtime.sock.close()
        self.runtime.sock = MagicMock()
        
        if hasattr(self.runtime, 'sd_sock') and self.runtime.sd_sock:
            self.runtime.sd_sock.close()
        self.runtime.sd_sock = MagicMock()
        
    def tearDown(self):
        # Close mocked sockets to avoid ResourceWarning
        if hasattr(self.runtime, 'sock') and self.runtime.sock:
             self.runtime.sock.close()
        if hasattr(self.runtime, 'sd_sock') and self.runtime.sd_sock:
             self.runtime.sd_sock.close()
        self.runtime.stop()

    def test_handle_sd_offer_parsing(self):
        """[PRS_SOMEIPSD_00016] Verify SD Packet Header & [PRS_SOMEIPSD_00019] Service Entry Parsing"""
        # Construct a valid SD Offer Packet manually to test _handle_sd_packet
        # Header (16 bytes) + SD Flags/Len (8 bytes) + Entry (16) + Option (12)
        
        # SD Flags (1) + Res (3) + Len (4)
        # Entry: Type 0x01 (Offer), Index1=0, Index2=0, NumOpts=10 (1 opt, 0 res)
        # ServiceID=0x1234, InstID=0x0001, TTL=0xFFFF, MinVer=0
        
        # Options: IPv4 (Len 9, Type 0x04, IP, Proto, Port)
        
        flags = 0x80
        sd_header = struct.pack(">BBBB", flags, 0, 0, 0)
        len_entries = 16
        sd_header += struct.pack(">I", len_entries) # Length of entries
        
        entry = struct.pack(">BBBBHHII", 
            0x01, # Type Offer
            0, 0, # Index 1, 2
            0x10, # 1 Option
            0x1234, 0x0001, # SID, IID
            0x00FFFFFF, # TTL
            0x00000000 # MinVer
        )
        
        len_options = 12
        opt_header = struct.pack(">I", len_options)
        
        # Option: Len=9, Type=0x04, Res, IP(127.0.0.1), Res, Proto(UDP), Port(9999)
        ip_int = struct.unpack(">I", socket.inet_aton("127.0.0.1"))[0]
        option = struct.pack(">HBBI BBH", 9, 0x04, 0, ip_int, 0, 0x11, 9999)
        
        # Full Payload starting from after SOME/IP Header
        # _handle_sd_packet expects the WHOLE packet including SOME/IP header?
        # Code: `offset = 16`. `flags = data[offset]`. Yes.
        
        someip_header = b'\x00' * 16 # Dummy header
        data = someip_header + sd_header + entry + opt_header + option
        
        self.runtime._handle_sd_packet(data, ('127.0.0.1', 30490), "test_alias")
        
        # Verify
        # TTL was 0x00FFFFFF. Major Version = (TTL >> 24) & 0xFF = 0.
        self.assertIn((0x1234, 0), self.runtime.remote_services)
        self.assertEqual(self.runtime.remote_services[(0x1234, 0)], ("127.0.0.1", 9999, 'udp'))

    def test_subscribe_eventgroup_flow(self):
        # Test sending subscription
        self.runtime.sd_sock = MagicMock()
        self.runtime.sd_sock_v6 = MagicMock()
        
        self.runtime.subscribe_eventgroup(0x1000, 1, 5, ttl=100)
        # subscribe_eventgroup only stores state; SD Subscribe packet sending is TODO
        
        # Verify subscription state is stored
        self.assertIn((0x1000, 5), self.runtime.subscriptions)
        self.assertTrue(self.runtime.subscriptions[(0x1000, 5)])
        
        # Simulate receiving an SD entry (type 0x07 = SubscribeAck)
        # Note: _handle_sd_packet currently only processes type 0x01 (Offer),
        # so SubscribeAck won't change state — verify no crash and state persists.
        entry_ack = struct.pack(">BBBBHHII", 
            0x07, 0, 0, 0, 
            0x1000, 1, 
            0x00FFFF, 
            0x00050000
        )
        
        sd_header = struct.pack(">BBBB", 0x80, 0, 0, 0) + struct.pack(">I", 16)
        opt_header = struct.pack(">I", 0)
        packet = b'\x00' * 16 + sd_header + entry_ack + opt_header
        
        self.runtime._handle_sd_packet(packet, ('127.0.0.1', 30490), "test_alias")
        # Subscription state should still be present (ack handling not yet implemented)
        self.assertIn((0x1000, 5), self.runtime.subscriptions)

    def test_unsubscribe(self):
        self.runtime.sd_sock = MagicMock()
        self.runtime.sd_sock_v6 = MagicMock()
        self.runtime.subscriptions[(0x1000, 5)] = True
        
        self.runtime.unsubscribe_eventgroup(0x1000, 1, 5)
        # Should remove from dict
        self.assertNotIn((0x1000, 5), self.runtime.subscriptions)

if __name__ == '__main__':
    unittest.main()
