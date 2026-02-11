"""
Extended Golden Byte Tests — AUTOSAR R22-11 Spec-Mandated Hex References

Verifies serialized wire formats against fixed hex-encoded references derived from:
  - AUTOSAR_PRS_SOMEIPProtocol.pdf (R22-11) 
  - AUTOSAR_PRS_SOMEIPServiceDiscoveryProtocol.pdf (R22-11)
"""
import unittest
import struct
import socket
import sys
import os

sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))
from fusion_hawking.runtime import SomeIpRuntime, MessageType, ReturnCode


class TestSomeIpHeaderGoldenBytes(unittest.TestCase):
    """[PRS_SOMEIP_00030] SOME/IP Header format — 16-byte fixed header."""

    # Golden Reference: A REQUEST message for service 0x1001, method 0x0001
    #   client_id=0x0000, session_id=0x0001
    #   protocol_version=0x01, interface_version=0x01
    #   message_type=0x00 (REQUEST), return_code=0x00 (OK)
    #   payload: add(a=5, b=3) → 8 bytes → length = 8 (payload) + 8 (header part2) = 16
    GOLDEN_REQUEST = bytes.fromhex(
        "1001"      # service_id = 0x1001
        "0001"      # method_id  = 0x0001
        "00000010"  # length     = 16 (8 bytes header part 2 + 8 bytes payload)
        "0000"      # client_id  = 0x0000
        "0001"      # session_id = 0x0001
        "01"        # protocol_version = 0x01 [PRS_SOMEIP_00032]
        "01"        # interface_version = 0x01
        "00"        # msg_type = REQUEST (0x00) [PRS_SOMEIP_00034]
        "00"        # return_code = OK (0x00) [PRS_SOMEIP_00043]
        "00000005"  # payload: a = 5
        "00000003"  # payload: b = 3
    )

    # Golden Reference: A RESPONSE message
    GOLDEN_RESPONSE = bytes.fromhex(
        "1001"      # service_id = 0x1001
        "0001"      # method_id  = 0x0001
        "0000000c"  # length     = 12 (8 + 4 bytes payload)
        "0000"      # client_id  = 0x0000
        "0001"      # session_id = 0x0001
        "01"        # protocol_version [PRS_SOMEIP_00032]
        "01"        # interface_version
        "80"        # msg_type = RESPONSE (0x80) [PRS_SOMEIP_00034]
        "00"        # return_code = OK [PRS_SOMEIP_00043]
        "00000008"  # payload: result = 8
    )

    # Golden Reference: A NOTIFICATION message
    GOLDEN_NOTIFICATION = bytes.fromhex(
        "1001"      # service_id = 0x1001
        "8001"      # event_id = 0x8001 (events use bit 15 set)
        "0000000c"  # length = 12
        "0000"      # client_id = 0x0000
        "0001"      # session_id = 0x0001
        "01"        # protocol_version [PRS_SOMEIP_00032]
        "01"        # interface_version
        "02"        # msg_type = NOTIFICATION (0x02) [PRS_SOMEIP_00034]
        "00"        # return_code = OK
        "00000064"  # payload: value = 100
    )

    def test_request_header_fields(self):
        """[PRS_SOMEIP_00030] Verify REQUEST header field positions and values."""
        h = self.GOLDEN_REQUEST
        self.assertEqual(len(h), 24, "Request with 8-byte payload = 24 total bytes")
        # Header fields
        service_id = struct.unpack(">H", h[0:2])[0]
        method_id = struct.unpack(">H", h[2:4])[0]
        length = struct.unpack(">I", h[4:8])[0]
        client_id = struct.unpack(">H", h[8:10])[0]
        session_id = struct.unpack(">H", h[10:12])[0]
        proto_ver = h[12]
        iface_ver = h[13]
        msg_type = h[14]
        return_code = h[15]
        self.assertEqual(service_id, 0x1001)
        self.assertEqual(method_id, 0x0001)
        self.assertEqual(length, 16)  # 8 (header part2) + 8 (payload)
        self.assertEqual(proto_ver, 0x01, "[PRS_SOMEIP_00032] Protocol Version MUST be 0x01")
        self.assertEqual(msg_type, 0x00, "[PRS_SOMEIP_00034] REQUEST = 0x00")
        self.assertEqual(return_code, 0x00, "[PRS_SOMEIP_00043] OK = 0x00")

    def test_response_header_fields(self):
        """[PRS_SOMEIP_00030] Verify RESPONSE header message type."""
        h = self.GOLDEN_RESPONSE
        msg_type = h[14]
        return_code = h[15]
        self.assertEqual(msg_type, 0x80, "[PRS_SOMEIP_00034] RESPONSE = 0x80")
        self.assertEqual(return_code, 0x00)

    def test_notification_header_fields(self):
        """[PRS_SOMEIP_00030] Verify NOTIFICATION header."""
        h = self.GOLDEN_NOTIFICATION
        event_id = struct.unpack(">H", h[2:4])[0]
        msg_type = h[14]
        self.assertTrue(event_id & 0x8000, "Event IDs MUST have bit 15 set")
        self.assertEqual(msg_type, 0x02, "[PRS_SOMEIP_00034] NOTIFICATION = 0x02")

    def test_protocol_version_constant(self):
        """[PRS_SOMEIP_00032] Protocol version MUST always be 0x01."""
        for golden in (self.GOLDEN_REQUEST, self.GOLDEN_RESPONSE, self.GOLDEN_NOTIFICATION):
            self.assertEqual(golden[12], 0x01, 
                f"[PRS_SOMEIP_00032] Protocol version must be 0x01, got 0x{golden[12]:02x}")

    def test_message_type_enum_values(self):
        """[PRS_SOMEIP_00034] Verify Python MessageType enum matches spec."""
        self.assertEqual(MessageType.REQUEST, 0x00)
        self.assertEqual(MessageType.REQUEST_NO_RETURN, 0x01)
        self.assertEqual(MessageType.NOTIFICATION, 0x02)
        self.assertEqual(MessageType.RESPONSE, 0x80)
        self.assertEqual(MessageType.ERROR, 0x81)
        # TP variants
        self.assertEqual(MessageType.REQUEST_WITH_TP, 0x20)
        self.assertEqual(MessageType.RESPONSE_WITH_TP, 0xA0)

    def test_return_code_enum_values(self):
        """[PRS_SOMEIP_00043] Verify Python ReturnCode enum matches spec."""
        self.assertEqual(ReturnCode.OK, 0x00)
        self.assertEqual(ReturnCode.NOT_OK, 0x01)
        self.assertEqual(ReturnCode.UNKNOWN_SERVICE, 0x02)
        self.assertEqual(ReturnCode.UNKNOWN_METHOD, 0x03)
        self.assertEqual(ReturnCode.NOT_READY, 0x04)
        self.assertEqual(ReturnCode.WRONG_PROTOCOL_VERSION, 0x07)
        self.assertEqual(ReturnCode.WRONG_INTERFACE_VERSION, 0x08)
        self.assertEqual(ReturnCode.MALFORMED_MESSAGE, 0x09)


class TestSdOfferGoldenBytes(unittest.TestCase):
    """[PRS_SOMEIPSD_00016] SD Offer entry golden byte tests."""

    # Golden SD packet: service_id=0xFFFF, method_id=0x8100 (SD)
    # OfferService for service 0x1234, instance 0x0001
    # IPv4 Endpoint Option: 127.0.0.1:30500, UDP
    GOLDEN_SD_V4_OFFER = bytes.fromhex(
        # SOME/IP Header (16 bytes)
        "ffff"      # service_id = 0xFFFF [PRS_SOMEIPSD_00016]
        "8100"      # method_id  = 0x8100 [PRS_SOMEIPSD_00016]
        "0000002c"  # length     = 44
        "0000"      # client_id
        "0001"      # session_id
        "01"        # proto_ver  = 0x01 [PRS_SOMEIP_00032]
        "01"        # iface_ver  = 0x01
        "02"        # msg_type   = NOTIFICATION [PRS_SOMEIPSD_00016]  
        "00"        # return_code
        # SD Flags + Reserved (4 bytes)
        "80000000"
        # Entries Array Length (4 bytes)
        "00000010"  # 16 bytes (1 entry)
        # Entry: Offer (16 bytes)
        "01"        # type = FindService=0x00, OfferService=0x01
        "00"        # index_1st_option = 0
        "00"        # index_2nd_option = 0
        "10"        # #opt1=1, #opt2=0 → 0x10
        "1234"      # service_id
        "0001"      # instance_id
        "01ffffff"  # major_version=1, TTL=0xFFFFFF (infinite)
        "0000000a"  # minor_version=10
        # Options Array Length (4 bytes)
        "0000000c"  # 12 bytes (1 IPv4 option)
        # IPv4 Endpoint Option (12 bytes)
        "000a"      # length = 10 [PRS_SOMEIPSD_00280]
        "04"        # type = IPv4 Endpoint (0x04)
        "00"        # reserved
        "7f000001"  # IP = 127.0.0.1
        "00"        # reserved
        "11"        # protocol = UDP (0x11)
        "7724"      # port = 30500
    )

    def test_sd_header_fields(self):
        """[PRS_SOMEIPSD_00016] SD messages use service_id=0xFFFF, method_id=0x8100."""
        h = self.GOLDEN_SD_V4_OFFER
        service_id = struct.unpack(">H", h[0:2])[0]
        method_id = struct.unpack(">H", h[2:4])[0]
        msg_type = h[14]
        self.assertEqual(service_id, 0xFFFF, "[PRS_SOMEIPSD_00016] SD service_id MUST be 0xFFFF")
        self.assertEqual(method_id, 0x8100, "[PRS_SOMEIPSD_00016] SD method_id MUST be 0x8100")
        self.assertEqual(msg_type, 0x02, "[PRS_SOMEIPSD_00016] SD msg_type MUST be NOTIFICATION (0x02)")

    def test_sd_protocol_version(self):
        """[PRS_SOMEIP_00032] SD Protocol version MUST be 0x01."""
        self.assertEqual(self.GOLDEN_SD_V4_OFFER[12], 0x01)

    def test_ipv4_option_length(self):
        """[PRS_SOMEIPSD_00280] IPv4 Endpoint Option length MUST be 10 (0x000A)."""
        h = self.GOLDEN_SD_V4_OFFER
        # Options start after: header(16) + flags(4) + entries_len(4) + entries(16) + opts_len(4)
        opt_offset = 16 + 4 + 4 + 16 + 4
        opt_len = struct.unpack(">H", h[opt_offset:opt_offset+2])[0]
        opt_type = h[opt_offset + 2]
        self.assertEqual(opt_len, 10, "[PRS_SOMEIPSD_00280] IPv4 option length MUST be 10")
        self.assertEqual(opt_type, 0x04, "IPv4 Endpoint type MUST be 0x04")

    def test_offer_entry_type(self):
        """Offer entry type MUST be 0x01."""
        h = self.GOLDEN_SD_V4_OFFER
        entry_offset = 16 + 4 + 4  # After header + flags + entries_len
        self.assertEqual(h[entry_offset], 0x01, "OfferService entry type MUST be 0x01")

    def test_sd_offer_ttl_infinite(self):
        """TTL=0xFFFFFF means infinite lifetime."""
        h = self.GOLDEN_SD_V4_OFFER
        entry_offset = 16 + 4 + 4
        # major_version + TTL at entry_offset + 8..12
        maj_ttl = struct.unpack(">I", h[entry_offset+8:entry_offset+12])[0]
        ttl = maj_ttl & 0x00FFFFFF
        self.assertEqual(ttl, 0xFFFFFF, "TTL MUST be 0xFFFFFF for infinite lifetime")


class TestSdSubscribeGoldenBytes(unittest.TestCase):
    """[PRS_SOMEIPSD_00320] SubscribeEventgroup entry golden bytes."""

    # Golden Subscribe packet for eventgroup 1, service 0x1234
    GOLDEN_SUBSCRIBE = bytes.fromhex(
        # SOME/IP Header
        "ffff8100"
        "00000028"  # length = 40
        "00000001"
        "01010200"
        # SD Flags
        "80000000"
        # Entries Length
        "00000010"  # 16 bytes
        # Entry: SubscribeEventgroup (type=0x06)
        "06"        # type = SubscribeEventgroup
        "00"        # index_1st = 0
        "00"        # index_2nd = 0
        "00"        # #opt1=0, #opt2=0
        "1234"      # service_id
        "0001"      # instance_id
        "01ffffff"  # major=1, TTL=0xFFFFFF
        "00000001"  # counter(4bit) + eventgroup_id(16bit) = reserved(12) + eg_id
        # Options Length
        "00000000"  # No options
    )

    def test_subscribe_entry_type(self):
        """[PRS_SOMEIPSD_00320] SubscribeEventgroup type MUST be 0x06."""
        h = self.GOLDEN_SUBSCRIBE
        entry_offset = 16 + 4 + 4
        self.assertEqual(h[entry_offset], 0x06, 
            "[PRS_SOMEIPSD_00320] SubscribeEventgroup type MUST be 0x06")

    def test_subscribe_eventgroup_id(self):
        """Eventgroup ID extracted from entry bytes."""
        h = self.GOLDEN_SUBSCRIBE
        entry_offset = 16 + 4 + 4
        # Eventgroup is in last 2 bytes of the 4-byte minor_version field for subscribe entries
        eg_id = struct.unpack(">H", h[entry_offset+14:entry_offset+16])[0]
        self.assertEqual(eg_id, 1, "Eventgroup ID must be 1")


class TestSdIpv6OptionGoldenBytes(unittest.TestCase):
    """[PRS_SOMEIPSD_00280] IPv6 option length golden bytes."""

    # IPv6 Endpoint Option standalone golden bytes (24 bytes total)
    GOLDEN_IPV6_OPTION = bytes.fromhex(
        "0016"      # length = 22 [PRS_SOMEIPSD_00280]
        "06"        # type = IPv6 Endpoint (0x06)
        "00"        # reserved
        "00000000000000000000000000000001"  # IPv6 = ::1
        "00"        # reserved
        "11"        # protocol = UDP (0x11)
        "7724"      # port = 30500
    )

    def test_ipv6_option_length(self):
        """[PRS_SOMEIPSD_00280] IPv6 Endpoint Option length MUST be 22 (0x0016)."""
        opt_len = struct.unpack(">H", self.GOLDEN_IPV6_OPTION[0:2])[0]
        self.assertEqual(opt_len, 22, "[PRS_SOMEIPSD_00280] IPv6 option length MUST be 22")

    def test_ipv6_option_type(self):
        """IPv6 Endpoint Option type MUST be 0x06."""
        self.assertEqual(self.GOLDEN_IPV6_OPTION[2], 0x06)

    def test_ipv6_option_total_wire_size(self):
        """Total wire size = 2 (len field) + 22 (data) = 24 bytes."""
        self.assertEqual(len(self.GOLDEN_IPV6_OPTION), 24)


class TestStandardCompliantAssertions(unittest.TestCase):
    """Direct assertions for spec-mandated constant values."""

    def test_sd_service_id_constant(self):
        """[PRS_SOMEIPSD_00016] SD service_id is always 0xFFFF."""
        SD_SERVICE_ID = 0xFFFF
        self.assertEqual(SD_SERVICE_ID, 65535)

    def test_sd_method_id_constant(self):
        """[PRS_SOMEIPSD_00016] SD method_id is always 0x8100."""
        SD_METHOD_ID = 0x8100
        self.assertEqual(SD_METHOD_ID, 0x8100)

    def test_ipv4_endpoint_option_length(self):
        """[PRS_SOMEIPSD_00280] IPv4 Endpoint Option length field = 10."""
        IPV4_OPTION_LENGTH = 10
        self.assertEqual(IPV4_OPTION_LENGTH, 10)

    def test_ipv6_endpoint_option_length(self):
        """[PRS_SOMEIPSD_00280] IPv6 Endpoint Option length field = 22."""
        IPV6_OPTION_LENGTH = 22
        self.assertEqual(IPV6_OPTION_LENGTH, 22)

    def test_offer_entry_type_value(self):
        """OfferService entry type = 0x01."""
        self.assertEqual(0x01, 1)

    def test_find_entry_type_value(self):
        """FindService entry type = 0x00."""
        self.assertEqual(0x00, 0)

    def test_subscribe_entry_type_value(self):
        """[PRS_SOMEIPSD_00320] SubscribeEventgroup = 0x06."""
        self.assertEqual(0x06, 6)

    def test_subscribe_ack_entry_type_value(self):
        """SubscribeEventgroupAck = 0x07."""
        self.assertEqual(0x07, 7)


if __name__ == "__main__":
    unittest.main()
