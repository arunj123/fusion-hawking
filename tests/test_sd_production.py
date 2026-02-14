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
            { 
                "providing": { 
                    "dummy_v4": { "service_id": 0x9999, "endpoint": "unicast-ep-v4", "interfaces": ["lo"] },
                    "dummy_v6": { "service_id": 0x9999, "endpoint": "unicast-ep-v6", "interfaces": ["lo"] }
                }
            }, 
            {
                "lo": {
                    "name": "lo",
                    "sd": { "endpoint_v4": "sd-mcast", "endpoint_v6": "sd-mcast-v6" },
                    "endpoints": {
                        "sd-mcast": { "ip": "224.0.0.1", "port": 30490, "version": 4 },
                        "sd-mcast-v6": { "ip": "ff02::1", "port": 30490, "version": 6 },
                        "unicast-ep-v4": { "ip": "127.0.0.1", "port": 30501, "version": 4, "protocol": "udp" },
                        "unicast-ep-v6": { "ip": "::1", "port": 30502, "version": 6, "protocol": "udp" }
                    }
                }
            },
            {}
        )
        """Verify the binary layout of an offer produced by the Python runtime."""
        # Setup a dummy runtime
        rt = SomeIpRuntime(None, "test", None)
        
        rt._send_offer(0x1234, 1, 1, 0, 30500, "127.0.0.1", "udp", "lo")
        
        # The runtime sends both IPv4 and IPv6 offers in Dual-Stack mode
        self.assertGreaterEqual(mock_sendto.call_count, 1)
        
        # Find the IPv4 packet among calls (first call is our offer)
        ipv4_call_data = None
        for args in mock_sendto.call_args_list:
            data = args[0][0]
            if len(data) > 16:  # Must be at least a SOME/IP header
                ipv4_call_data = data
                break
        
        self.assertIsNotNone(ipv4_call_data, "Should have sent an IPv4 offer")
        
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
        opt_len_field = struct.unpack(">H", sd_payload[28:30])[0]
        self.assertEqual(opt_len_field, 9, "Option Length field should be 9 (excludes Type field)")
        
        opt_type = sd_payload[30]
        self.assertEqual(opt_type, 0x04, "Option Type should be 0x04 (IPv4)")

if __name__ == '__main__':
    unittest.main()
