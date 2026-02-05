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
    @patch('socket.socket.sendto')
    def test_python_offer_layout(self, mock_sendto):
        """Verify the binary layout of an offer produced by the Python runtime."""
        # Setup a dummy runtime
        rt = SomeIpRuntime(None, "test", None)
        rt.interface_ip = "127.0.0.1"
        
        rt._send_offer(0x1234, 1, 30500)
        
        self.assertTrue(mock_sendto.called)
        data = mock_sendto.call_args[0][0]
        
        # SOME/IP Header (16 bytes)
        self.assertEqual(len(data), 16 + 40) # 16 Header + 40 SD Payload
        
        # SOME/IP-SD Payload starts at 16
        sd_payload = data[16:]
        
        # Options Length is at index 16 (Header) + 8 (SD Header) + 16 (Entry) = 40?
        # Offset 16: SD Header (4)
        # Offset 20: Entries Len (4)
        # Offset 24: Entry (16)
        # Offset 40: Options Len (4)
        options_len = struct.unpack(">I", sd_payload[24:28])[0]
        self.assertEqual(options_len, 12, "Options Len should be exactly 12 for one IPv4 option")
        
        # Option structure check
        # Offset 28: Option Len (2)
        # Offset 30: Option Type (1)
        opt_len_field = struct.unpack(">H", sd_payload[28:30])[0]
        self.assertEqual(opt_len_field, 9, "Option Length field should be 9 (bytes after Type)")
        
        opt_type = sd_payload[30]
        self.assertEqual(opt_type, 0x04, "Option Type should be 0x04 (IPv4)")

if __name__ == '__main__':
    unittest.main()
