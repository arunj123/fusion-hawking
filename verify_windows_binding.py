import socket
import struct
import sys
import time
import threading

# Configuration
MCAST_GRP = '224.224.224.245'
MCAST_PORT = 31000
IFACE_IP = '127.0.0.1' # Loopback for Windows test

def receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    print(f"Binding to {IFACE_IP}:{MCAST_PORT} (Unicast IP)...")
    try:
        sock.bind((IFACE_IP, MCAST_PORT))
    except Exception as e:
        print(f"Bind failed: {e}")
        return

    # Join Multicast Group
    try:
        mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GRP), socket.inet_aton(IFACE_IP))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print("Joined multicast group.")
    except Exception as e:
        print(f"Join failed: {e}")
        return

    sock.settimeout(3)
    try:
        data, addr = sock.recvfrom(1024)
        print(f"Received: {data} from {addr}")
    except socket.timeout:
        print("Timed out waiting for data.")

def sender():
    time.sleep(1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE_IP))
    print(f"Sending to {MCAST_GRP}:{MCAST_PORT}...")
    sock.sendto(b"Verified!", (MCAST_GRP, MCAST_PORT))

if __name__ == "__main__":
    t = threading.Thread(target=receiver)
    t.start()
    sender()
    t.join()
