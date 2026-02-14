import socket
import struct
import time
import sys

M_IP = "224.0.0.3"
PORT = 30890
IFACE_IP = "192.168.0.113"

def run_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))
    print(f"Receiver bound to ANY:{PORT}")

    mreq = struct.pack("4s4s", socket.inet_aton(M_IP), socket.inet_aton(IFACE_IP))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    sock.settimeout(5.0)
    
    print(f"Receiver joined {M_IP} on {IFACE_IP}, waiting...")
    try:
        data, addr = sock.recvfrom(1024)
        print(f"Receiver got: {data} from {addr}")
    except socket.timeout:
        print("Receiver timeout")

def run_sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Important: bind to a port so we have a source address
    sock.bind((IFACE_IP, 0))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE_IP))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    print(f"Sender sending from {sock.getsockname()} to {M_IP}:{PORT}")
    for i in range(3):
        sock.sendto(f"MESSAGE {i}".encode(), (M_IP, PORT))
        time.sleep(0.5)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        run_sender()
    else:
        run_receiver()
