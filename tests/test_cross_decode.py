"""
Cross-Language Decode Test — PCAP Binary Fixture Verification

Loads shared binary fixture files and verifies the Python parser decodes
them identically to spec expectations. The same fixtures are used by Rust
and C++ tests to ensure cross-language consistency.

Based on AUTOSAR R22-11 (PRS_SOMEIPProtocol, PRS_SOMEIPServiceDiscoveryProtocol).
"""
import unittest
import struct
import os
import glob
import sys

sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))
from fusion_hawking.runtime import MessageType, ReturnCode

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def parse_someip_header(data: bytes) -> dict:
    """Parse a SOME/IP header from raw bytes. Returns dict or None if too short."""
    if len(data) < 16:
        return None
    service_id, method_id = struct.unpack(">HH", data[0:4])
    length = struct.unpack(">I", data[4:8])[0]
    client_id, session_id = struct.unpack(">HH", data[8:12])
    proto_ver, iface_ver, msg_type, return_code = struct.unpack("BBBB", data[12:16])
    return {
        "service_id": service_id,
        "method_id": method_id,
        "length": length,
        "client_id": client_id,
        "session_id": session_id,
        "protocol_version": proto_ver,
        "interface_version": iface_ver,
        "message_type": msg_type,
        "return_code": return_code,
        "payload": data[16:],
    }


def parse_sd_entries(data: bytes, offset: int) -> list:
    """Parse SD entries starting at given offset."""
    if offset + 4 > len(data):
        return []
    entries_len = struct.unpack(">I", data[offset:offset+4])[0]
    entries = []
    pos = offset + 4
    end = pos + entries_len
    while pos + 16 <= end:
        entry = {
            "type": data[pos],
            "index_1st": data[pos+1],
            "index_2nd": data[pos+2],
            "num_opts": data[pos+3],
            "service_id": struct.unpack(">H", data[pos+4:pos+6])[0],
            "instance_id": struct.unpack(">H", data[pos+6:pos+8])[0],
            "major_version": data[pos+8],
            "ttl": struct.unpack(">I", b'\x00' + data[pos+9:pos+12])[0],
            "minor_version": struct.unpack(">I", data[pos+12:pos+16])[0],
        }
        entries.append(entry)
        pos += 16
    return entries


def parse_sd_options(data: bytes, offset: int) -> list:
    """Parse SD options starting at given offset."""
    if offset + 4 > len(data):
        return []
    opts_len = struct.unpack(">I", data[offset:offset+4])[0]
    options = []
    pos = offset + 4
    end = pos + opts_len
    while pos + 4 <= end:
        opt_len = struct.unpack(">H", data[pos:pos+2])[0]
        opt_type = data[pos+2]
        opt_data = data[pos+4:pos+2+opt_len] if pos+2+opt_len <= end else b''
        options.append({
            "length": opt_len,
            "type": opt_type,
            "data": opt_data,
        })
        pos += 2 + opt_len
    return options


def load_fixture(name: str) -> bytes:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "rb") as f:
        return f.read()


class TestRpcRequestDecode(unittest.TestCase):
    """Decode rpc_request.bin and verify all fields."""

    def setUp(self):
        self.data = load_fixture("rpc_request.bin")

    def test_header_parse(self):
        h = parse_someip_header(self.data)
        self.assertIsNotNone(h)
        self.assertEqual(h["service_id"], 0x1001)
        self.assertEqual(h["method_id"], 0x0001)
        self.assertEqual(h["length"], 16)
        self.assertEqual(h["protocol_version"], 0x01)
        self.assertEqual(h["message_type"], MessageType.REQUEST)
        self.assertEqual(h["return_code"], ReturnCode.E_OK)

    def test_payload_decode(self):
        h = parse_someip_header(self.data)
        payload = h["payload"]
        self.assertEqual(len(payload), 8)
        a = struct.unpack(">i", payload[0:4])[0]
        b = struct.unpack(">i", payload[4:8])[0]
        self.assertEqual(a, 5)
        self.assertEqual(b, 3)


class TestRpcResponseDecode(unittest.TestCase):
    """Decode rpc_response.bin and verify all fields."""

    def setUp(self):
        self.data = load_fixture("rpc_response.bin")

    def test_header_parse(self):
        h = parse_someip_header(self.data)
        self.assertIsNotNone(h)
        self.assertEqual(h["message_type"], MessageType.RESPONSE)
        self.assertEqual(h["return_code"], ReturnCode.E_OK)

    def test_payload_decode(self):
        h = parse_someip_header(self.data)
        result = struct.unpack(">i", h["payload"][0:4])[0]
        self.assertEqual(result, 8)


class TestSdOfferV4Decode(unittest.TestCase):
    """Decode sd_offer_v4.bin and verify SD structure."""

    def setUp(self):
        self.data = load_fixture("sd_offer_v4.bin")

    def test_sd_header(self):
        h = parse_someip_header(self.data)
        self.assertEqual(h["service_id"], 0xFFFF)
        self.assertEqual(h["method_id"], 0x8100)
        self.assertEqual(h["message_type"], 0x02)  # NOTIFICATION

    def test_sd_flags(self):
        flags = self.data[16]
        self.assertTrue(flags & 0x80, "Reboot flag should be set")

    def test_sd_entries(self):
        # Entries start at offset 20 (header 16 + flags 4)
        entries = parse_sd_entries(self.data, 20)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], 0x01)  # OfferService
        self.assertEqual(entries[0]["service_id"], 0x1234)
        self.assertEqual(entries[0]["instance_id"], 0x0001)
        self.assertEqual(entries[0]["major_version"], 1)
        self.assertEqual(entries[0]["ttl"], 0xFFFFFF)

    def test_sd_options(self):
        # Options start after entries: offset 20+4+16 = 40
        options = parse_sd_options(self.data, 40)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["length"], 10, "[PRS_SOMEIPSD_00280] IPv4 len=10")
        self.assertEqual(options[0]["type"], 0x04)  # IPv4 Endpoint


class TestSdOfferV6Decode(unittest.TestCase):
    """Decode sd_offer_v6.bin and verify IPv6 option."""

    def setUp(self):
        self.data = load_fixture("sd_offer_v6.bin")

    def test_sd_options_v6(self):
        options = parse_sd_options(self.data, 40)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["length"], 22, "[PRS_SOMEIPSD_00280] IPv6 len=22")
        self.assertEqual(options[0]["type"], 0x06)  # IPv6 Endpoint


class TestMalformedPackets(unittest.TestCase):
    """Verify parser handles malformed packets gracefully."""

    def test_truncated_packet(self):
        """Short packet (<16 bytes) should not parse."""
        data = load_fixture("malformed_short.bin")
        h = parse_someip_header(data)
        self.assertIsNone(h, "Truncated packet MUST return None")

    def test_incorrect_length(self):
        """Packet with incorrect length field should still parse header."""
        data = load_fixture("malformed_length.bin")
        h = parse_someip_header(data)
        self.assertIsNotNone(h)
        # Length field says 1000, but actual payload is only 4 bytes
        self.assertEqual(h["length"], 1000)
        actual_payload = len(h["payload"])
        self.assertLess(actual_payload, 1000, 
            "Actual payload must be less than claimed length")

    def test_notification_wrong_return_code(self):
        """Notification with non-zero return code should parse but be detectable."""
        data = load_fixture("malformed_notification.bin")
        h = parse_someip_header(data)
        self.assertIsNotNone(h)
        self.assertEqual(h["message_type"], 0x02)  # NOTIFICATION
        self.assertNotEqual(h["return_code"], 0x00, 
            "Return code should be non-zero (malformed per spec)")


if __name__ == "__main__":
    unittest.main()
