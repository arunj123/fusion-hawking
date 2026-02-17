import unittest
import struct
import time
import threading
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'python')))

from fusion_hawking.runtime import SomeIpRuntime, MessageType, RequestHandler
from fusion_hawking.tp import TpHeader

class MockHandler(RequestHandler):
    def __init__(self, sid):
        self.sid = sid
        self.received_payload = None

    def get_service_id(self):
        return self.sid

    def handle(self, header, payload):
        self.received_payload = payload
        # Return a large payload to trigger TX segmentation
        return b'R' * 2000

class TestRuntimeTp(unittest.TestCase):
    def setUp(self):
        # Create a dummy config
        self.config_path = os.path.abspath("test_config_tp.json")
        with open(self.config_path, "w") as f:
            f.write('{"instances": {"test_inst": {}}, "interfaces": {"eth0": {"endpoints": {"ep1": {"ip": "127.0.0.1", "port": 1234}}}}}')
            
    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    @patch('fusion_hawking.runtime.select.select')
    @patch('socket.socket')
    def test_rx_reassembly_and_tx_segmentation(self, mock_socket_cls, mock_select):
        # Setup mocks
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recvfrom.return_value = (None, None) # Default
        mock_sock.fileno.return_value = 100

        # Configure select to return mock_sock twice then empty
        mock_select.side_effect = [
            ([mock_sock], [], []), # 1 -> recvfrom calls (pkt1)
            ([mock_sock], [], []), # 2 -> recvfrom calls (pkt2)
            ([mock_sock], [], []), # 3 -> recvfrom calls (None)
            ([], [], [])           # 4 -> Sleep
        ]
        
        # Initialize Runtime
        rt = SomeIpRuntime(self.config_path, "test_inst")
        rt.interfaces = {"eth0": {"endpoints": {"ep1": {"ip": "127.0.0.1", "port": 1234}}}} # Mock config overrides
        
        # Register Handler
        handler = MockHandler(0x1234)
        rt.services[0x1234] = handler
        
        # Prepare TP Segments for RX
        # Segment 1: Offset 0, More=True, 16 bytes
        # Segment 2: Offset 16, More=False, 4 bytes
        sid, mid, cid, ssid = 0x1234, 0x0001, 0x1000, 0x0001
        
        # TP Header 1: Off=0, More=1 -> 0x00000001
        tp1 = struct.pack(">I", 1)
        # Msg Header 1: Len = 8 + 4 (TP) + 16 (Payload) = 28
        h1 = struct.pack(">HHIHH4B", sid, mid, 28, cid, ssid, 1, 1, 0x20, 0)
        p1 = b'A' * 16
        pkt1 = h1 + tp1 + p1
        
        # TP Header 2: Off=16, More=0 -> (1<<4)|0 = 0x10 -> 0x00000010
        tp2 = struct.pack(">I", 0x10)
        # Msg Header 2: Len = 8 + 4 (TP) + 4 (Payload) = 16
        h2 = struct.pack(">HHIHH4B", sid, mid, 16, cid, ssid, 1, 1, 0x20, 0)
        p2 = b'B' * 4
        pkt2 = h2 + tp2 + p2
        
        # Setup Mock Socket to return packets
        mock_sock.type = 2 # UDP
        mock_sock.recvfrom.side_effect = [
            (pkt1, ("127.0.0.1", 9999)),
            (pkt2, ("127.0.0.1", 9999)),
            (None, None) # Stop
        ]
        
        # Inject mock socket into listeners
        rt.listeners = {("127.0.0.1", 1234, "udp"): mock_sock}
        
        rt.start()
        
        # Wait for processing
        time.sleep(0.2)
        
        rt.stop()
        
        # Verification RX
        expected_payload = b'A' * 16 + b'B' * 4
        self.assertEqual(handler.received_payload, expected_payload)
        
        # Verification TX
        # The handler returns 2000 bytes. MAX_SEG_PAYLOAD is 1392.
        # Should be split into 2 segments: 1392 + 608.
        # Check sendto calls
        self.assertTrue(mock_sock.sendto.called)
        call_args_list = mock_sock.sendto.call_args_list
        
        # Filter for actual response packets (ignoring explicit SD logs if any)
        # We expect 2 calls.
        segment_calls = [c for c in call_args_list if len(c[0][0]) > 20] # Filter small keepalives if any
        
        self.assertGreaterEqual(len(segment_calls), 2)
        
        # Seg 1
        data1 = segment_calls[0][0][0]
        # Check TP Header presence
        # 16 (MsgHeader) + 4 (TPHeader)
        # MsgType should be RESPONSE_WITH_TP (0xA0)
        mt1 = data1[14]
        self.assertEqual(mt1, 0xA0)
        
        tp_h1_val = struct.unpack(">I", data1[16:20])[0]
        # Offset 0, More=1 -> 1
        self.assertEqual(tp_h1_val, 1)
        
        # Seg 2
        data2 = segment_calls[1][0][0]
        mt2 = data2[14]
        self.assertEqual(mt2, 0xA0)
        
        tp_h2_val = struct.unpack(">I", data2[16:20])[0]
        # Offset 1392 (0x570). 0x570 / 16 = 0x57 = 87.
        # Val = (87 << 4) | 0 = 1392.
        expected_val = ( (1392 // 16) << 4 ) | 0
        self.assertEqual(tp_h2_val, expected_val)
        
if __name__ == '__main__':
    unittest.main()
