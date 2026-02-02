"""Comprehensive serialization tests for Python bindings."""
import unittest
import sys
import os
import struct

# Add build/generated/python and src/python to path
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))

from bindings import (
    MathServiceAddRequest, MathServiceAddResponse,
    StringServiceReverseRequest, StringServiceReverseResponse,
    SortServiceSortAscRequest, SortServiceSortAscResponse
)


class TestIntSerialization(unittest.TestCase):
    """Test integer serialization (big-endian)."""
    
    def test_positive_int(self):
        """Test positive integer serialization."""
        req = MathServiceAddRequest(100, 200)
        data = req.serialize()
        
        # 4 bytes for 'a' + 4 bytes for 'b' = 8 bytes
        self.assertEqual(len(data), 8)
        
        # Verify big-endian encoding
        # 100 = 0x00000064
        self.assertEqual(data[:4], struct.pack('>i', 100))
        # 200 = 0x000000C8
        self.assertEqual(data[4:], struct.pack('>i', 200))
    
    def test_negative_int(self):
        """Test negative integer serialization (two's complement)."""
        req = MathServiceAddRequest(-50, -100)
        data = req.serialize()
        
        # -50 = 0xFFFFFFCE
        self.assertEqual(data[:4], struct.pack('>i', -50))
        # -100 = 0xFFFFFF9C
        self.assertEqual(data[4:], struct.pack('>i', -100))
    
    def test_zero(self):
        """Test zero serialization."""
        req = MathServiceAddRequest(0, 0)
        data = req.serialize()
        
        self.assertEqual(data, b'\x00\x00\x00\x00\x00\x00\x00\x00')
    
    def test_boundary_values(self):
        """Test int32 min/max boundary values."""
        # Max int32
        req_max = MathServiceAddRequest(2147483647, 0)
        data_max = req_max.serialize()
        self.assertEqual(data_max[:4], struct.pack('>i', 2147483647))
        
        # Min int32
        req_min = MathServiceAddRequest(-2147483648, 0)
        data_min = req_min.serialize()
        self.assertEqual(data_min[:4], struct.pack('>i', -2147483648))


class TestStringSerialization(unittest.TestCase):
    """Test string serialization (length-prefixed UTF-8)."""
    
    def test_simple_string(self):
        """Test simple ASCII string serialization."""
        req = StringServiceReverseRequest("Hello")
        data = req.serialize()
        
        # Format: length (4 bytes) + UTF-8 bytes
        # "Hello" = 5 bytes
        self.assertEqual(len(data), 4 + 5)
        
        # Length field in big-endian
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, 5)
        
        # String content
        self.assertEqual(data[4:], b'Hello')
    
    def test_empty_string(self):
        """Test empty string serialization."""
        req = StringServiceReverseRequest("")
        data = req.serialize()
        
        # Just length = 0
        self.assertEqual(len(data), 4)
        self.assertEqual(data, b'\x00\x00\x00\x00')
    
    def test_unicode_string(self):
        """Test Unicode string serialization."""
        req = StringServiceReverseRequest("こんにちは")  # Japanese "Hello"
        data = req.serialize()
        
        # UTF-8 encoding of "こんにちは" = 15 bytes (3 bytes per character)
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, 15)
        
        # Verify UTF-8 encoding
        self.assertEqual(data[4:], "こんにちは".encode('utf-8'))
    
    def test_special_characters(self):
        """Test strings with special characters."""
        req = StringServiceReverseRequest("Hello\nWorld\t!")
        data = req.serialize()
        
        expected = "Hello\nWorld\t!".encode('utf-8')
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, len(expected))
        self.assertEqual(data[4:], expected)


class TestListSerialization(unittest.TestCase):
    """Test list/vector serialization."""
    
    def test_int_list(self):
        """Test integer list serialization."""
        req = SortServiceSortAscRequest([10, 20, 30, 40, 50])
        data = req.serialize()
        
        # Format: byte_length (4 bytes) + elements
        # 5 elements * 4 bytes = 20 bytes
        self.assertEqual(len(data), 4 + 20)
        
        # Length field (in bytes, not elements)
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, 20)
        
        # Verify elements
        for i, val in enumerate([10, 20, 30, 40, 50]):
            offset = 4 + (i * 4)
            elem = struct.unpack('>i', data[offset:offset+4])[0]
            self.assertEqual(elem, val)
    
    def test_empty_list(self):
        """Test empty list serialization."""
        req = SortServiceSortAscRequest([])
        data = req.serialize()
        
        # Just length = 0
        self.assertEqual(len(data), 4)
        self.assertEqual(data, b'\x00\x00\x00\x00')
    
    def test_negative_numbers_in_list(self):
        """Test list with negative numbers."""
        req = SortServiceSortAscRequest([-100, -50, 0, 50, 100])
        data = req.serialize()
        
        # Verify negative numbers use two's complement
        offset = 4
        elem = struct.unpack('>i', data[offset:offset+4])[0]
        self.assertEqual(elem, -100)
    
    def test_single_element_list(self):
        """Test single element list."""
        req = SortServiceSortAscRequest([42])
        data = req.serialize()
        
        self.assertEqual(len(data), 4 + 4)  # length + 1 element
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, 4)
        
        elem = struct.unpack('>i', data[4:])[0]
        self.assertEqual(elem, 42)


class TestResponseSerialization(unittest.TestCase):
    """Test response struct serialization."""
    
    def test_int_response(self):
        """Test integer response serialization."""
        resp = MathServiceAddResponse(300)
        data = resp.serialize()
        
        self.assertEqual(len(data), 4)
        result = struct.unpack('>i', data)[0]
        self.assertEqual(result, 300)
    
    def test_string_response(self):
        """Test string response serialization."""
        resp = StringServiceReverseResponse("dlroW olleH")
        data = resp.serialize()
        
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, 11)
        self.assertEqual(data[4:], b'dlroW olleH')
    
    def test_list_response(self):
        """Test list response serialization."""
        resp = SortServiceSortAscResponse([1, 2, 3, 4, 5])
        data = resp.serialize()
        
        length = struct.unpack('>I', data[:4])[0]
        self.assertEqual(length, 20)  # 5 * 4 bytes


if __name__ == '__main__':
    unittest.main()
