
import socket
import struct
import sys
import time
import threading

MCAST_GRP = '224.224.224.245'
MCAST_PORT = 30491
RECV_IP = '10.0.1.2'
SEND_IP = '10.0.1.1'

def receiver():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', MCAST_PORT)) # Bind to ALL for easier join
    # Join on specific interface IP
    mreq = struct.pack('4s4s', socket.inet_aton(MCAST_GRP), socket.inet_aton(RECV_IP))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    s.settimeout(5)
    print('LISTENING')
    sys.stdout.flush()
    try:
        data, addr = s.recvfrom(1024)
        print(f'RECEIVED:{data.decode()} FROM:{addr[0]}')
    except Exception as e:
        print(f'ERROR:{e}')

t = threading.Thread(target=receiver)
t.start()
time.sleep(2)

# Sender
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((SEND_IP, 0))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(SEND_IP))
    s.sendto(b'VNET_MSG', (MCAST_GRP, MCAST_PORT))
    print('SENT')
    sys.stdout.flush()
except Exception as e:
    print(f'SEND_ERROR:{e}')

t.join()
