import unittest
import struct
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'python')))

from fusion_hawking.tp import TpHeader, segment_payload, TpReassembler

class TestTp(unittest.TestCase):
    def test_header_serialization(self):
        # Test 1: Offset 0, More Segments = True
        h = TpHeader(0, True)
        data = h.serialize()
        # Val = (0 << 4) | 1 = 1
        self.assertEqual(data, b'\x00\x00\x00\x01')
        
        # Test 2: Offset 16, More Segments = False
        h2 = TpHeader(16, False)
        data2 = h2.serialize()
        # Val = (1 << 4) | 0 = 16 (0x10)
        self.assertEqual(data2, b'\x00\x00\x00\x10')
        
        # Test 3: Deserialize
        h3 = TpHeader.deserialize(b'\x00\x00\x00\x11')
        self.assertEqual(h3.offset, 16)
        self.assertTrue(h3.more_segments)

    def test_segmentation(self):
        payload = b'A' * 40
        # Split into chunks of 16 bytes (plus header)
        # Max payload per segment = 16
        segments = segment_payload(payload, 16)
        
        self.assertEqual(len(segments), 3)
        
        # Seg 1: 16 bytes, More=True
        self.assertEqual(len(segments[0][1]), 16)
        self.assertTrue(segments[0][0].more_segments)
        self.assertEqual(segments[0][0].offset, 0)
        
        # Seg 2: 16 bytes, More=True
        self.assertEqual(len(segments[1][1]), 16)
        self.assertTrue(segments[1][0].more_segments)
        self.assertEqual(segments[1][0].offset, 16)
        
        # Seg 3: 8 bytes, More=False
        self.assertEqual(len(segments[2][1]), 8)
        self.assertFalse(segments[2][0].more_segments)
        self.assertEqual(segments[2][0].offset, 32)
        
    def test_reassembly(self):
        reassembler = TpReassembler()
        key = (1, 1, 1, 1)
        
        payload = b'B' * 40
        segments = segment_payload(payload, 16)
        
        # Process in order
        self.assertIsNone(reassembler.process_segment(key, segments[0][0], segments[0][1]))
        self.assertIsNone(reassembler.process_segment(key, segments[1][0], segments[1][1]))
        
        # Last segment
        result = reassembler.process_segment(key, segments[2][0], segments[2][1])
        self.assertEqual(result, payload)
        
    def test_reassembly_out_of_order(self):
        reassembler = TpReassembler()
        key = (2, 2, 2, 2)
        
        payload = b'C' * 40
        segments = segment_payload(payload, 16)
        
        # Process: 2, 0, 1
        self.assertIsNone(reassembler.process_segment(key, segments[2][0], segments[2][1]))
        self.assertIsNone(reassembler.process_segment(key, segments[0][0], segments[0][1]))
        
        result = reassembler.process_segment(key, segments[1][0], segments[1][1])
        self.assertEqual(result, payload)

if __name__ == '__main__':
    unittest.main()
