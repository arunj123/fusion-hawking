import socket
import struct
import sys
import threading
import time
import subprocess
import os
import psutil

# --- Configuration for Research ---
# Control Path: Used for Service Discovery (Simulating SOME/IP SD)
SD_GROUP = '239.0.0.1'
SD_PORT = 30490

# Data Path: Used for Event/Data Publication
DATA_GROUP = '239.0.0.10'
DATA_PORT = 30491

# Buffer size for receiving
BUFFER_SIZE = 1024

def get_primary_interface_ip():
    """
    Identifies the IP address of the primary network interface using a 
    portable approach compatible with Windows and POSIX.
    """
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    
    # Priority list for interface names (common on Windows and Linux)
    priority_keywords = ['eth', 'en', 'wlan', 'ethernet', 'wi-fi']
    
    found_interfaces = []
    
    for nic, addr_list in addrs.items():
        if nic in stats and stats[nic].isup:
            for addr in addr_list:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    found_interfaces.append((nic, addr.address))
    
    # Sort based on priority keywords to find the most "physical" interface
    for keyword in priority_keywords:
        for nic, ip in found_interfaces:
            if keyword in nic.lower():
                return ip
                
    # Fallback to the first available non-loopback IP
    if found_interfaces:
        return found_interfaces[0][1]
    
    # Ultimate fallback
    return socket.gethostbyname(socket.gethostname())

def setup_multicast_socket(mcast_group, port, interface_ip):
    """
    Creates and configures a hardened multicast socket using 
    standard socket options compatible with Winsock and POSIX.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    # Portable: Allow address reuse. 
    # Note: On some POSIX systems, SO_REUSEPORT might also be needed for 
    # multiple processes to bind to the same multicast port.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except socket.error:
            pass # Not supported on all platforms/kernels

    # Bind strictly to the identified hardware interface IP
    try:
        sock.bind((interface_ip, port))
    except Exception as e:
        print(f"Error binding to {interface_ip}:{port}: {e}")
        sys.exit(1)

    # Join the multicast group on the specific interface (Portable binary format)
    # imr_multiaddr + imr_interface
    mreq = struct.pack("4s4s", socket.inet_aton(mcast_group), socket.inet_aton(interface_ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    # Set the outgoing interface for multicast transmissions
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))
    
    # Set TTL (Time To Live). 1 = Local Network Segment only.
    # Higher values allow crossing routers (common in automotive VLANs).
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    
    return sock

def listen_loop(sock, path_name, node_id):
    """Generic thread function to listen and print incoming data."""
    while True:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            msg = data.decode('utf-8', errors='ignore')
            if f"ID:{node_id}" not in msg:
                print(f"[{path_name} Node {node_id}] RECV from {addr}: {msg}")
        except Exception:
            break

def run_node(node_id):
    """Logic for an individual node running both paths."""
    interface_ip = get_primary_interface_ip()
    print(f"--- Node {node_id} Active on {interface_ip} ---")

    sd_sock = setup_multicast_socket(SD_GROUP, SD_PORT, interface_ip)
    data_sock = setup_multicast_socket(DATA_GROUP, DATA_PORT, interface_ip)

    t1 = threading.Thread(target=listen_loop, args=(sd_sock, "CONTROL", node_id), daemon=True)
    t2 = threading.Thread(target=listen_loop, args=(data_sock, "DATA   ", node_id), daemon=True)
    t1.start()
    t2.start()

    counter = 0
    try:
        while True:
            # Control Path: Service Discovery
            sd_msg = f"SD_OFFER | ID:{node_id} | Srv:0x1234 | Inst:1".encode('utf-8')
            sd_sock.sendto(sd_msg, (SD_GROUP, SD_PORT))

            # Data Path: Event Publishing
            if counter % 2 == 0:
                data_msg = f"EVENT_DATA | ID:{node_id} | Payload:{counter}".encode('utf-8')
                data_sock.sendto(data_msg, (DATA_GROUP, DATA_PORT))

            time.sleep(2)
            counter += 1
    except KeyboardInterrupt:
        print(f"Node {node_id} shutting down.")
    finally:
        sd_sock.close()
        data_sock.close()

def main_manager():
    """Management Mode for orchestrating the research session."""
    interface_ip = get_primary_interface_ip()
    print("="*60)
    print("PORTABLE MULTICAST SEPARATION RESEARCH TOOL")
    print(f"Detected Interface: {interface_ip}")
    print(f"Control Group:      {SD_GROUP}:{SD_PORT}")
    print(f"Data Group:         {DATA_GROUP}:{DATA_PORT}")
    print("="*60)
    print("Launching Node A and Node B...\n")

    process_a = subprocess.Popen([sys.executable, __file__, "A"])
    process_b = subprocess.Popen([sys.executable, __file__, "B"])

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down research nodes...")
        process_a.terminate()
        process_b.terminate()
        print("Done.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_node(sys.argv[1])
    else:
        main_manager()