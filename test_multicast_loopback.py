import socket
import struct
import time
import threading

M_IP = "224.0.0.3"
PORT = 30890
IFACE_IP = "127.0.0.1"

def receiver(name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", PORT))
        print(f"Receiver {name} bound to ANY:{PORT}")
    except Exception as e:
        print(f"Receiver {name} bind failed: {e}")
        return

    mreq = struct.pack("4s4s", socket.inet_aton(M_IP), socket.inet_aton(IFACE_IP))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    # Important: some stacks require IP_MULTICAST_LOOP for EACH socket
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    sock.settimeout(5.0)
    
    print(f"Receiver {name} joined {M_IP} on {IFACE_IP}, waiting...")
    try:
        data, addr = sock.recvfrom(1024)
        print(f"Receiver {name} got: {data} from {addr}")
    except socket.timeout:
        print(f"Receiver {name} timeout")
    except Exception as e:
        print(f"Receiver {name} error: {e}")

def sender():
    time.sleep(1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Ensure sender also joined or at least uses the right IF
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE_IP))
    print(f"Sender sending to {M_IP}:{PORT} via {IFACE_IP}")
    sock.sendto(b"HELLO MULTICAST", (M_IP, PORT))

if __name__ == "__main__":
    t1 = threading.Thread(target=receiver, args=("R1",))
    t2 = threading.Thread(target=receiver, args=("R2",))
    t1.start()
    t2.start()
    sender()
    t1.join()
    t2.join()
