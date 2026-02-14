import socket
import struct
import sys
import os
import subprocess
import time
import threading
import fcntl

# Configuration
MULTICAST_GROUP = '226.1.1.1'
PORT = 12345
INTERFACE = 'veth0'  # Target interface within the namespace

def set_kernel_param(param, value):
    """
    Sets a kernel parameter via sysctl. 
    Crucial for safety-relevant testing to ensure the stack doesn't 
    silently drop packets due to RP Filter or routing logic.
    Ref: https://man7.org/linux/man-pages/man7/ip.7.html
    """
    try:
        subprocess.run(["sysctl", "-w", f"{param}={value}"], check=True, capture_output=True)
    except Exception as e:
        print(f"Warning: Failed to set {param}: {e}")

def get_ip_address(ifname):
    """
    Retrieves the Unicast IP address of the specified interface using ioctl.
    This ensures we know which hardware interface we are using.
    Ref: SIOCGIFADDR in https://man7.org/linux/man-pages/man7/netdevice.7.html
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        return socket.inet_ntoa(fcntl.ioctl(
            s.fileno(),
            0x8915,  # SIOCGIFADDR
            struct.pack('256s', ifname[:15].encode('utf-8'))
        )[20:24])
    except OSError:
        print(f"Error: Could not find IP for interface {ifname}")
        sys.exit(1)

def run_agent(name):
    """
    The agent logic running inside the namespace.
    Implements strict binding and multicast group management.
    """
    # 1. System Hardening: Disable RP Filter to allow multicast traffic
    set_kernel_param(f"net.ipv4.conf.{INTERFACE}.rp_filter", 0)
    set_kernel_param("net.ipv4.conf.all.rp_filter", 0)

    local_ip = get_ip_address(INTERFACE)
    ifindex = socket.if_nametoindex(INTERFACE)
    
    print(f"[{name}] Starting Agent...")
    print(f"[{name}] Local IP: {local_ip}")
    print(f"[{name}] Interface: {INTERFACE} (Index: {ifindex})")

    # 2. Receiver Socket Setup
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # --- SAFETY FIX ---
    # In Linux, if you bind to a Unicast IP (10.0.1.x), the kernel drops packets 
    # destined for a Multicast IP (226.1.1.1) because the destination doesn't match.
    # To fix this while staying "strict", we bind to the MULTICAST GROUP address.
    # This ensures the kernel passes 226.1.1.1 traffic to this socket.
    try:
        rx_sock.bind((MULTICAST_GROUP, PORT))
        print(f"[{name}] Successfully bound to Group {MULTICAST_GROUP}:{PORT}")
    except Exception as e:
        print(f"[{name}] Bind failed: {e}")
        return

    # Strict Hardware Binding: Locks the socket to the physical interface
    try:
        rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, INTERFACE.encode())
    except PermissionError:
        print(f"[{name}] Permission denied for SO_BINDTODEVICE")

    # Join Multicast Group using ip_mreqn (using the LOCAL_IP for explicit membership)
    mreqn = struct.pack("4s4si", 
                        socket.inet_aton(MULTICAST_GROUP), 
                        socket.inet_aton(local_ip), 
                        ifindex)
    
    rx_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreqn)

    # 3. Sender Socket Setup
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    # Ensure outgoing multicast packets only go through the designated local_ip interface
    tx_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip))
    tx_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    def receiver_loop():
        rx_sock.settimeout(1.0)
        while True:
            try:
                data, addr = rx_sock.recvfrom(1024)
                if addr[0] != local_ip:
                    print(f"[{name}] <--- RECV: '{data.decode()}' from {addr[0]}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[{name}] RX Error: {e}")
                break

    threading.Thread(target=receiver_loop, daemon=True).start()

    try:
        while True:
            msg = f"Heartbeat from {name}"
            tx_sock.sendto(msg.encode(), (MULTICAST_GROUP, PORT))
            print(f"[{name}] ---> SENT heartbeat to {MULTICAST_GROUP}")
            time.sleep(3)
    except KeyboardInterrupt:
        print(f"[{name}] Shutting down...")

def main():
    if len(sys.argv) > 1:
        run_agent(sys.argv[1])
        return

    if os.getuid() != 0:
        print("Error: Manager must be run with sudo.")
        sys.exit(1)

    namespaces = ["ns_ecu1", "ns_ecu2", "ns_ecu3"]
    processes = []

    print("=== Multicast Safety Verification Management ===")
    print(f"Target Group: {MULTICAST_GROUP}:{PORT}")
    
    script_path = os.path.abspath(__file__)

    for ns in namespaces:
        cmd = ["ip", "netns", "exec", ns, "python3", "-u", script_path, ns]
        p = subprocess.Popen(cmd)
        processes.append(p)
        print(f"Launched Agent in {ns} (PID: {p.pid})")

    try:
        print("\nVerifying communication... (Press Ctrl+C to stop)\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nOrchestrator stopping agents...")
        for p in processes:
            p.terminate()
            p.wait()
        print("Clean exit.")

if __name__ == "__main__":
    main()