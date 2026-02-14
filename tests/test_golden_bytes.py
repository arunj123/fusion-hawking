import unittest
import struct
import socket
import sys
import os

# Add src/python to path
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))
from fusion_hawking.runtime import SomeIpRuntime

class TestGoldenBytes(unittest.TestCase):
    def test_python_v4_offer_golden(self):
        """Verify Python-generated v4 Offer matches a standard-compliant layout."""
        from unittest.mock import patch
        with patch('fusion_hawking.runtime.SomeIpRuntime._load_config') as mock_load:
            mock_load.return_value = (
                { 
                    "sd": { "multicast_endpoint": "sd-mcast", "multicast_endpoint_v6": "sd-mcast-v6" },
                    "providing": { 
                        "dummy_v4": { "service_id": 0x1234, "endpoint": "unicast-ep-v4" },
                        "dummy_v6": { "service_id": 0x1234, "endpoint": "unicast-ep-v6" } 
                    }
                }, 
                { 
                    "lo": {
                        "name": "lo",
                        "sd": { "endpoint": "sd-mcast", "endpoint_v6": "sd-mcast-v6" },
                        "endpoints": {
                            "sd-mcast": { "ip": "224.0.0.1", "port": 30490, "version": 4, "interface": "lo" },
                            "sd-mcast-v6": { "ip": "ff02::1", "port": 30490, "version": 6, "interface": "lo" },
                            "unicast-ep-v4": { "ip": "127.0.0.1", "port": 30500, "version": 4, "interface": "lo" },
                            "unicast-ep-v6": { "ip": "::1", "port": 30501, "version": 6, "interface": "lo" }
                        }
                    }
                },
                {}
            )
            rt = SomeIpRuntime(None, "test", None)
            
            with patch('socket.socket.sendto') as mock_send:
                # service_id=0x1234, instance=1, major=1, minor=10, port=30500
                # Force v4 usage logic in runtime requires valid IP
                rt._send_offer(0x1234, 1, 1, 10, 30500, "127.0.0.1", "udp", "lo")
                
                # Find IPv4 call
                ipv4_data = None
                for call in mock_send.call_args_list:
                    if call[0][1][0] == "224.0.0.1":
                        ipv4_data = call[0][0]
                        break
                
                self.assertIsNotNone(ipv4_data)
                opt_len = struct.unpack(">H", ipv4_data[44:46])[0]
                self.assertEqual(opt_len, 9, "Standard requires 9 for IPv4 Endpoint option")

    def test_python_v6_offer_golden(self):
        """Verify Python-generated v6 Offer matches a standard-compliant layout."""
        from unittest.mock import patch
        with patch('fusion_hawking.runtime.SomeIpRuntime._load_config') as mock_load:
            mock_load.return_value = (
                { 
                    "sd": { "multicast_endpoint": "sd-mcast", "multicast_endpoint_v6": "sd-mcast-v6" },
                    "providing": { 
                        "dummy_v4": { "service_id": 0x1234, "endpoint": "unicast-ep-v4" },
                        "dummy_v6": { "service_id": 0x1234, "endpoint": "unicast-ep-v6" } 
                    }
                }, 
                { 
                    "lo": {
                        "name": "lo",
                        "sd": { "endpoint": "sd-mcast", "endpoint_v6": "sd-mcast-v6" },
                        "endpoints": {
                            "sd-mcast": { "ip": "224.0.0.1", "port": 30490, "version": 4, "interface": "lo" },
                            "sd-mcast-v6": { "ip": "ff02::1", "port": 30490, "version": 6, "interface": "lo" },
                            "unicast-ep-v4": { "ip": "127.0.0.1", "port": 30500, "version": 4, "interface": "lo" },
                            "unicast-ep-v6": { "ip": "::1", "port": 30501, "version": 6, "interface": "lo" }
                        }
                    }
                },
                {}
            )
            rt = SomeIpRuntime(None, "test", None)
            
            with patch('socket.socket.sendto') as mock_send:
                rt._send_offer(0x1234, 1, 1, 10, 30501, "::1", "udp", "lo")
                
                # Find v6 call
                v6_data = None
                for call in mock_send.call_args_list:
                    if len(call[0][0]) > 60:
                        v6_data = call[0][0]
                        break
                
                self.assertIsNotNone(v6_data)
                opt_len = struct.unpack(">H", v6_data[44:46])[0]
                self.assertEqual(opt_len, 21, "Standard requires 21 for IPv6 Endpoint option")

if __name__ == "__main__":
    unittest.main()
