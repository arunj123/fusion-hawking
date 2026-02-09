import unittest
import sys
import os
import struct
import socket

# Add src/python to path
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))
from fusion_hawking.runtime import SomeIpRuntime

class TestSdPacketProduction(unittest.TestCase):
    from unittest.mock import patch
    @patch('fusion_hawking.runtime.SomeIpRuntime._load_config')
    @patch('socket.socket.sendto')
    def test_python_offer_layout(self, mock_sendto, mock_load_config):
        # Mock config to satisfy runtime init checks
        mock_load_config.return_value = (
            { "sd": { "multicast_endpoint": "sd-mcast" } }, 
            { "sd-mcast": { "ip": "224.0.0.1", "port": 30490, "version": 4, "interface": "lo" } }
        )
        """Verify the binary layout of an offer produced by the Python runtime."""
        # Setup a dummy runtime
        rt = SomeIpRuntime(None, "test", None)
        rt.interface_ip = "127.0.0.1"
        rt.interface_ip_v6 = "::1"
        
        rt._send_offer(0x1234, 1, 1, 0, 30500)
        
        # The runtime sends both IPv4 and IPv6 offers in Dual-Stack mode
        self.assertGreaterEqual(mock_sendto.call_count, 1)
        
        # Find the IPv4 packet among calls
        ipv4_call_data = None
        for args in mock_sendto.call_args_list:
            data = args[0][0]
            addr = args[0][1]
            if addr[0] == rt.sd_multicast_ip:
                ipv4_call_data = data
                break
        
        self.assertIsNotNone(ipv4_call_data, "Should have sent an IPv4 offer")
        
        # 16 bytes SOME/IP Header + SD Payload
        # SD Payload: Flags(4) + EntriesLen(4) + Entry(16) + OptionsLen(4) + Option(12) = 40 bytes
        self.assertEqual(len(ipv4_call_data), 16 + 40)
        
        sd_payload = ipv4_call_data[16:]
        
        # Entries Len is at offset 4
        entries_len = struct.unpack(">I", sd_payload[4:8])[0]
        self.assertEqual(entries_len, 16)
        
        # Options Len is at offset 8 (SD Header) + 16 (Entry) = 24
        options_len = struct.unpack(">I", sd_payload[24:28])[0]
        self.assertEqual(options_len, 12, "Options Len should be exactly 12 for one IPv4 option")
        
        # Option Header: Len(2) + Type(1) + Res(1) = 4 bytes.
        # Position: 24 (OptionsLen) + 4 = 28
        opt_len_field = struct.unpack(">H", sd_payload[28:30])[0]
        self.assertEqual(opt_len_field, 9, "Option Length field should be 9 (bytes after Type)")
        
        opt_type = sd_payload[30]
        self.assertEqual(opt_type, 0x04, "Option Type should be 0x04 (IPv4)")

if __name__ == '__main__':
    unittest.main()
