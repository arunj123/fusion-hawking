import socket
import struct
import time

def main():
    # 1. Client Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    
    # 2. Construct Request
    sid = 0x1234
    mid = 0x0001
    payload = b"Hello from Python"
    length = len(payload) + 8
    
    header = struct.pack(">HHIHH4B", 
        sid, mid, length, 
        0xDEAD, 0xBEEF, # Client/Session
        0x01, 0x01,     # Proto/Iface Ver
        0x00, 0x00      # Type (Req), RC
    )
    
    # 3. Send to Server (Assuming Python Server on 40001)
    target = ('127.0.0.1', 40001)
    print(f"Sending Request to {target}")
    sock.sendto(header + payload, target)
    
    # 4. Receive
    try:
        data, addr = sock.recvfrom(1500)
        if len(data) >= 16:
            mt = data[14]
            if mt == 0x80:
                print("Success: Got Response!")
                if len(data) > 16:
                    print(f"Payload: {data[16:]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
