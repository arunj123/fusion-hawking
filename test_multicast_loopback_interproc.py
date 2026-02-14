import socket
import struct
import time
import sys
import threading

MCAST_GRP = '224.0.0.5'
PORT = 30894 # Match someipy
IFACE_IP = '127.0.0.1'

def receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind to ANY
    sock.bind(("", PORT))
    
    # Join on loopback
    mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GRP), socket.inet_aton(IFACE_IP))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    print(f"Receiver: Bound to ANY:{PORT}, joined {MCAST_GRP} on {IFACE_IP}")
    sock.settimeout(5)
    try:
        data, addr = sock.recvfrom(1024)
        print(f"Receiver: Received '{data.decode()}' from {addr}")
    except socket.timeout:
        print("Receiver: TIMEOUT")

def sender():
    time.sleep(1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    # Set interface for sending
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE_IP))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    
    msg = "Hello Loopback Multicast!"
    print(f"Sender: Sending '{msg}' to {MCAST_GRP}:{PORT} on {IFACE_IP}")
    sock.sendto(msg.encode(), (MCAST_GRP, PORT))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "recv":
            receiver()
        else:
            sender()
    else:
        # Run both in threads
        r = threading.Thread(target=receiver)
        s = threading.Thread(target=sender)
        r.start()
        s.start()
        r.join()
        s.join()
