import struct
import socket

def generate_golden_v4_offer():
    # SOME/IP Header
    header = struct.pack(">HHIHH4B", 0xFFFF, 0x8100, 40+8, 0, 1, 1, 1, 2, 0)
    
    # SD Payload
    flags = 0x80000000
    sd_header = struct.pack(">I", flags)
    
    # Entries
    entries_len = struct.pack(">I", 16)
    entry = struct.pack(">BBBBHHII", 0x01, 0, 0, 0x10, 0x1234, 1, (1 << 24) | 0xFFFFFF, 10)
    
    # Options
    # Total options len = 12
    options_len = struct.pack(">I", 12)
    # Option: Len=10, Type=0x04, Res=0, IP=127.0.0.1, Res=0, Proto=0x11, Port=30500
    ip_int = struct.unpack(">I", socket.inet_aton("127.0.0.1"))[0]
    option = struct.pack(">HBBI BBH", 10, 0x04, 0, ip_int, 0, 0x11, 30500)
    
    full_packet = header + sd_header + entries_len + entry + options_len + option
    return full_packet.hex()

if __name__ == "__main__":
    print(f"Golden v4 Offer: {generate_golden_v4_offer()}")
