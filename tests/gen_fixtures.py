"""
Generate binary fixture files for cross-language fuzzing tests.
These fixtures contain valid and malformed SOME/IP packets per AUTOSAR R22-11.
"""
import struct
import os

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(FIXTURES_DIR, exist_ok=True)

def write_fixture(name, data):
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    print(f"  Created {name} ({len(data)} bytes)")


# --- Valid Packets ---

# 1. RPC Request: service=0x1001, method=0x0001, payload=add(5,3)
rpc_request = bytes.fromhex(
    "10010001"   # service_id | method_id
    "00000010"   # length = 16
    "00000001"   # client_id=0, session_id=1
    "01010000"   # proto=1, iface=1, msg_type=REQUEST, return_code=OK
    "0000000500000003"  # payload: a=5, b=3
)
write_fixture("rpc_request.bin", rpc_request)

# 2. RPC Response: service=0x1001, method=0x0001, payload=result=8
rpc_response = bytes.fromhex(
    "10010001"
    "0000000c"   # length = 12
    "00000001"
    "01018000"   # msg_type=RESPONSE(0x80)
    "00000008"   # result=8
)
write_fixture("rpc_response.bin", rpc_response)

# 3. SD Offer with IPv4 Endpoint
sd_offer_v4 = bytes.fromhex(
    "ffff8100"                  # SD service/method
    "0000002c"                  # length=44
    "00000001"                  # client=0, session=1
    "01010200"                  # notification
    "80000000"                  # flags: reboot=1
    "00000010"                  # entries_len=16
    "01000010"                  # Offer, idx1=0, idx2=0, #opt1=1
    "12340001"                  # service=0x1234, instance=1
    "01ffffff"                  # major=1, TTL=infinite
    "0000000a"                  # minor=10
    "0000000c"                  # options_len=12
    "000a0400"                  # IPv4 option: len=10, type=0x04
    "7f000001"                  # 127.0.0.1
    "00117724"                  # UDP, port=30500
)
write_fixture("sd_offer_v4.bin", sd_offer_v4)

# 4. SD Offer with IPv6 Endpoint
sd_offer_v6 = bytes.fromhex(
    "ffff8100"
    "00000038"                  # length=56
    "00000001"
    "01010200"
    "80000000"
    "00000010"
    "01000010"
    "12340001"
    "01ffffff"
    "0000000a"
    "00000018"                  # options_len=24
    "00160600"                  # IPv6 option: len=22, type=0x06
    "00000000000000000000000000000001"  # ::1
    "00117724"                  # UDP, port=30500
)
write_fixture("sd_offer_v6.bin", sd_offer_v6)

# --- Malformed Packets ---

# 5. Truncated packet (< 16 bytes — incomplete header)
malformed_short = bytes.fromhex("1001000100000010")  # Only 8 bytes
write_fixture("malformed_short.bin", malformed_short)

# 6. Packet with incorrect length field (claims 1000 bytes but only has 4)
malformed_length = bytes.fromhex(
    "10010001"
    "000003e8"   # length claims 1000
    "00000001"
    "01010000"
    "00000005"   # Only 4 bytes of payload
)
write_fixture("malformed_length.bin", malformed_length)

# 7. Notification with wrong return code (should be 0x00 for notifications)
malformed_notification = bytes.fromhex(
    "10018001"
    "0000000c"
    "00000001"
    "01010201"   # msg_type=NOTIFICATION but return_code=NOT_OK (invalid)
    "00000064"
)
write_fixture("malformed_notification.bin", malformed_notification)

print(f"\nGenerated {len(os.listdir(FIXTURES_DIR))} fixture files in {FIXTURES_DIR}")
