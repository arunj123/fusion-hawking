import socket
import struct

def main():
    # 1. Bind to fixed port
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 40001))
    print("Simple Python Server listening on 127.0.0.1:40001")

    while True:
        data, addr = sock.recvfrom(1500)
        if len(data) < 16: continue

        print(f"Received {len(data)} bytes from {addr}")

        # 2. Parse Header
        # Format: >HHIHH4B
        sid, mid, length, cid, ssid, pv, iv, mt, rc = struct.unpack(">HHIHH4B", data[:16])
        print(f"  Service: 0x{sid:04x}, Method: 0x{mid:04x}, Type: 0x{mt:02x}")

        # 3. Send Response
        if mt == 0x00: # Request
            print("  Sending Response...")
            
            # Response: Change Type to 0x80 (Response), RC to 0x00 (OK)
            payload = b"Python OK"
            res_len = len(payload) + 8
            
            res_header = struct.pack(">HHIHH4B", 
                sid, mid, res_len, 
                cid, ssid, pv, iv, 
                0x80, 0x00
            )

            sock.sendto(res_header + payload, addr)

if __name__ == "__main__":
    main()
