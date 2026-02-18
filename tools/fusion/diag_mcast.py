import socket
import struct
import sys
import os
import subprocess
import time
import threading
import platform

# Optional dependency for interface discovery on Windows
try:
    import psutil
except ImportError:
    psutil = None

# Optional dependency for ioctl on Linux
try:
    import fcntl
except ImportError:
    fcntl = None

# Configuration
MULTICAST_GROUP_DEFAULT = '226.1.1.1'
PORT_DEFAULT = 12345

def get_ip_address_linux(ifname):
    """Retrieves the Unicast IP address of the specified interface on Linux."""
    if not fcntl:
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        return socket.inet_ntoa(fcntl.ioctl(
            s.fileno(),
            0x8915,  # SIOCGIFADDR
            struct.pack('256s', ifname[:15].encode('utf-8'))
        )[20:24])
    except OSError:
        return None

def get_primary_interface_ip():
    """Identifies the IP address of the primary network interface (cross-platform)."""
    if psutil:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        priority_keywords = ['eth', 'en', 'wlan', 'ethernet', 'wi-fi', 'veth']
        found_interfaces = []
        for nic, addr_list in addrs.items():
            if nic in stats and stats[nic].isup:
                for addr in addr_list:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        found_interfaces.append((nic, addr.address))
        for keyword in priority_keywords:
            for nic, ip in found_interfaces:
                if keyword in nic.lower():
                    return ip, nic
        if found_interfaces:
            return found_interfaces[0][1], found_interfaces[0][0]
    
    # Fallback
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip, None
    except Exception:
        return socket.gethostbyname(socket.gethostname()), None

def setup_multicast_socket(mcast_group, port, interface_ip, interface_name=None):
    """Creates and configures a hardened multicast socket with strict binding."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except socket.error:
            pass

    # Platform-specific binding strategy
    if platform.system() == "Linux":
        # On Linux, binding to Unicast blocks multicast reception
        # Bind to Multicast Group IP instead
        try:
            sock.bind((mcast_group, port))
            if interface_name:
                sock.setsockopt(socket.SOL_SOCKET, 25, interface_name.encode()) # SO_BINDTODEVICE
        except Exception as e:
            print(f"Bind error (Linux): {e}")
            sys.exit(1)
    else:
        # Windows: Bind to Unicast IP
        try:
            sock.bind((interface_ip, port))
        except Exception as e:
            print(f"Bind error (Windows): {e}")
            sys.exit(1)

    # Membership
    ifindex = socket.if_nametoindex(interface_name) if interface_name else 0
    mreqn = struct.pack("4s4si", 
                        socket.inet_aton(mcast_group), 
                        socket.inet_aton(interface_ip), 
                        ifindex)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreqn)
    
    # Transmission setup
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    
    return sock

def run_agent(name, mcast_group, port, interface_name=None):
    """Runs a single diagnostic agent."""
    if interface_name and platform.system() == "Linux":
        local_ip = get_ip_address_linux(interface_name)
    else:
        local_ip, if_name = get_primary_interface_ip()
        interface_name = interface_name or if_name

    print(f"[{name}] Starting Diag Agent...")
    print(f"[{name}] Local IP: {local_ip}, Interface: {interface_name}")
    
    sock = setup_multicast_socket(mcast_group, port, local_ip, interface_name)
    
    def receiver_loop():
        sock.settimeout(1.0)
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if addr[0] != local_ip:
                    print(f"[{name}] <--- RECV from {addr[0]}: {data.decode()}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[{name}] RX Error: {e}")
                break

    threading.Thread(target=receiver_loop, daemon=True).start()
    
    try:
        while True:
            msg = f"Ping from {name} at {time.time()}"
            sock.sendto(msg.encode(), (mcast_group, port))
            time.sleep(2)
    except KeyboardInterrupt:
        print(f"[{name}] Shutting down...")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fusion Multicast Diagnostic Tool")
    parser.add_argument("--group", default=MULTICAST_GROUP_DEFAULT, help="Multicast Group IP")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT, help="UDP Port")
    parser.add_argument("--interface", help="Interface name (Linux) or index")
    parser.add_argument("--name", default="Node1", help="Agent name")
    parser.add_argument("--manager", action="store_true", help="Launch multiple agents (Linux namespaces)")
    
    args = parser.parse_args()

    if args.manager:
        if platform.system() != "Linux":
            print("Error: Manager mode requires Linux namespaces.")
            sys.exit(1)
        
        namespaces = ["ns_ecu1", "ns_ecu2", "ns_ecu3"]
        processes = []
        print("=== Multicast Diagnostic Manager ===")
        script_path = os.path.abspath(__file__)
        for ns in namespaces:
            # We assume 'veth0' exists in these namespaces per our standard setup
            cmd = ["ip", "netns", "exec", ns, sys.executable, "-u", script_path, "--name", ns, "--interface", "veth0"]
            p = subprocess.Popen(cmd)
            processes.append(p)
        
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            for p in processes: p.terminate()
            print("Done.")
    else:
        run_agent(args.name, args.group, args.port, args.interface)

if __name__ == "__main__":
    main()
