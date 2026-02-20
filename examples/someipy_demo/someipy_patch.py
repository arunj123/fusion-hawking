import socket
import struct
import platform
import os
import someipy._internal.utils as someipy_utils

def apply_patch():
    """
    Monkey-patches someipy's internal utils to support Windows Service Discovery sharing.
    This enables SO_REUSEADDR on Windows and ensures multicast/broadcast sockets
    bind to the wildcard address on Windows to allow multiple listeners.
    """
    
    def patched_create_udp_socket(ip_address: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((ip_address, port))
        return sock

    def patched_create_rcv_multicast_socket(ip_address: str, port: int, interface_address: str) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass

        if platform.system() == "Windows":
            # Windows specific: Bind to wildcard to allow sharing
            sock.bind(("", port))
        else:
            sock.bind((ip_address, port))

        mreq = struct.pack("4s4s", socket.inet_aton(ip_address), socket.inet_aton(interface_address))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        return sock

    def patched_create_rcv_broadcast_socket(ip_address: str, port: int, interface_address: str) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        if platform.system() == "Windows":
            sock.bind(("", port))
        else:
            sock.bind((ip_address, port))
        return sock

    # Apply patches
    someipy_utils.create_udp_socket = patched_create_udp_socket
    someipy_utils.create_rcv_multicast_socket = patched_create_rcv_multicast_socket
    someipy_utils.create_rcv_broadcast_socket = patched_create_rcv_broadcast_socket
    
    print("[Fusion] Applied someipy Windows SD sharing monkey-patch")
