import unittest
import struct
import socket
from unittest.mock import MagicMock, patch
from fusion_hawking.runtime import SessionIdManager, SomeIpRuntime, MessageType

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
        self.runtime = SomeIpRuntime(None, "test_instance")
        self.runtime.logger = MagicMock()
        # Mock sockets to prevent network activity
        self.runtime.sock = MagicMock()
        self.runtime.sd_sock = MagicMock()
        
    def tearDown(self):
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
        
        self.runtime._handle_sd_packet(data)
        
        # Verify
        self.assertIn(0x1234, self.runtime.remote_services)
        self.assertEqual(self.runtime.remote_services[0x1234], ("127.0.0.1", 9999))

    def test_subscribe_eventgroup_flow(self):
        # Test sending subscription
        with patch.object(self.runtime.sd_sock, 'sendto') as mock_send:
            self.runtime.subscribe_eventgroup(0x1000, 1, 5, ttl=100)
            mock_send.assert_called_once()
            
            # Verify subscription state
            self.assertIn((0x1000, 5), self.runtime.subscriptions)
            self.assertFalse(self.runtime.is_subscription_acked(0x1000, 5))
            
            # Now simulate receiving an ACK
            # Type 0x07 (Ack), same IDs
            entry_ack = struct.pack(">BBBBHHII", 
                0x07, # Type Ack
                0, 0, 0, # Indices, No options
                0x1000, 0x0001, # SID, IID
                0x00FFFF, # TTL (non-zero)
                (5 << 16) # Major Version contains EventgroupID in upper 16 bits??? 
                # Code: `eventgroup_id = min_ver >> 16` -> Wait. MinVer is last 4 bytes? 
                # Code line 265: `min_ver = struct.unpack(..., data[current+12:current+16])`
                # Code line 356: `eventgroup_id = min_ver >> 16`
                # So we must pack eventgroup id into the high bits of the last 4 bytes field?
                # In `subscribe_eventgroup` (line 377), `minor` field uses `eventgroup_id << 16`. 
                # In Ack parsing (line 356), it uses `min_ver`. 
                # entry format: ... Maj/TTL(4), Min(4).
                # line 377 packs `minor` as last args.
                # So yes, put 5 in high bits.
            )
            # 5 << 16 = 0x00050000
            entry_ack_corrected = struct.pack(">BBBBHHII", 
                0x07, 0, 0, 0, 
                0x1000, 0x0001, 
                0x000000FF, 
                0x00050000
            ) 
            
            sd_header = struct.pack(">BBBB", 0x80, 0, 0, 0) + struct.pack(">I", 16)
            opt_header = struct.pack(">I", 0) # No options
            
            packet = b'\x00' * 16 + sd_header + entry_ack_corrected + opt_header
            
            self.runtime._handle_sd_packet(packet)
            
            self.assertTrue(self.runtime.is_subscription_acked(0x1000, 5))

    def test_unsubscribe(self):
        self.runtime.subscriptions[(0x1000, 5)] = True
        with patch.object(self.runtime.sd_sock, 'sendto') as mock_send:
            self.runtime.unsubscribe_eventgroup(0x1000, 1, 5)
            # Should remove from dict
            self.assertFalse(self.runtime.is_subscription_acked(0x1000, 5))
            self.assertNotIn((0x1000, 5), self.runtime.subscriptions)

if __name__ == '__main__':
    unittest.main()
