
import socket
import struct
import sys
import time

MCAST_GRP = '224.224.224.245'
MCAST_PORT = 30491

def run_receiver(bind_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', MCAST_PORT))
    mreq = struct.pack('4s4s', socket.inet_aton(MCAST_GRP), socket.inet_aton(bind_ip))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    s.settimeout(5)
    print(f"RECEIVER_WAITING on {bind_ip}")
    sys.stdout.flush()
    try:
        data, addr = s.recvfrom(1024)
        print(f"RECEIVED:{data.decode()} FROM:{addr[0]}")
    except Exception as e:
        print(f"ERROR:{e}")

def run_sender(send_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(send_ip))
    s.sendto(b"MCAST_TEST_MSG", (MCAST_GRP, MCAST_PORT))
    print(f"SENT from {send_ip}")

if __name__ == "__main__":
    role = sys.argv[1]
    ip = sys.argv[2]
    if role == "recv":
        run_receiver(ip)
    else:
        run_sender(ip)
