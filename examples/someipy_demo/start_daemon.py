import asyncio
import json
import sys
import os
import socket
import struct
import platform

# Add someipy to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../third_party/someipy/src")))

# Monkey-patch someipy for Windows support because it doesn't handle loopback-only multicast well
import someipy._internal.utils as someipy_utils

def patched_create_rcv_multicast_socket(ip_address: str, port: int, interface_address: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Windows specific fix: Bind to the wildcard address instead of the interface address
    # This allows multiple processes to share the multicast port on Windows
    if os.name == 'nt':
        sock.bind(("", port))
    else:
        sock.bind((ip_address, port))

    mreq = struct.pack("4s4s", socket.inet_aton(ip_address), socket.inet_aton(interface_address))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock

someipy_utils.create_rcv_multicast_socket = patched_create_rcv_multicast_socket

from someipy.someipyd import SomeipDaemon

async def main():
    # Basic configuration for the daemon
    config = {
        "services": [],
        "routing": {
            "use_tcp": True,
            "tcp_host": "127.0.0.1",
            "tcp_port": 30500
        }
    }
    
    # Normally someipy loads from a JSON, but we can also instantiate it.
    # However, someipyd.py is designed to be run as a script.
    # We'll just run it via subprocess or import and call its main if possible.
    
    print("[someipy Daemon] Starting daemon on 127.0.0.1:30500...")
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", nargs="?", default="client_config.json", help="Path to client configuration")
    parser.add_argument("--interface_ip", default="127.0.0.1", help="IP address to bind to")
    args = parser.parse_args()
    
    config_path = args.config_path
    interface_ip = args.interface_ip
    
    sd_port = 30491
    sd_addr = "224.0.0.1"
    
    # Try to extract interface IP from Fusion config if not explicitly provided as "127.0.0.1" (default)
    # This allows it to automatically find 10.0.1.x in VNet mode.
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
            # Support new config schema: interfaces -> primary -> endpoints
            if "interfaces" in cfg:
                iface = cfg["interfaces"].get("primary") or next(iter(cfg["interfaces"].values()))
                endpoints = iface["endpoints"]
                
                # Dynamic IP resolution: find the IP of this interface
                # We'll look for sd_uc_v4 first
                if "sd_uc_v4" in endpoints:
                    found_ip = endpoints["sd_uc_v4"]["ip"]
                    if interface_ip == "127.0.0.1" and found_ip != "127.0.0.1":
                         interface_ip = found_ip
                         print(f"[someipy Daemon] Resolved bind IP from config: {interface_ip}")
                
                if "sd_multicast" in endpoints:
                    sd_port = endpoints["sd_multicast"]["port"]
                    sd_addr = endpoints["sd_multicast"]["ip"]
                elif "sd_mcast_v4" in endpoints:
                    sd_port = endpoints["sd_mcast_v4"]["port"]
                    sd_addr = endpoints["sd_mcast_v4"]["ip"]
                else:
                    print(f"[someipy Daemon] Warning: Could not find sd_multicast or sd_mcast_v4 in endpoints: {list(endpoints.keys())}")
            else:
                # Fallback to old schema
                if "sd_multicast" in cfg["endpoints"]:
                    sd_port = cfg["endpoints"]["sd_multicast"]["port"]
                    sd_addr = cfg["endpoints"]["sd_multicast"]["ip"]
                elif "sd_mcast_v4" in cfg["endpoints"]:
                    sd_port = cfg["endpoints"]["sd_mcast_v4"]["port"]
                    sd_addr = cfg["endpoints"]["sd_mcast_v4"]["ip"]
                
            print(f"[someipy Daemon] Isolated SD: {sd_addr}:{sd_port} (from {config_path})")
    except Exception as e:
        print(f"[someipy Daemon] Could not read {config_path} or find endpoints, using defaults: {e}")

    # Import someipyd and run it
    import someipy.someipyd as someipyd
    import json as py_json
    
    # Create a dummy config file with dynamic SD port and address in the same directory as fusion config
    config_file = os.path.join(os.path.dirname(os.path.abspath(config_path)), "someipyd_config.json")
    print(f"[someipy Daemon] Writing internal config to: {config_file}")
    
    sys.argv = [sys.argv[0], "--config", config_file]
    
    with open(config_file, "w") as f:
        f.write(py_json.dumps({
            "interface": interface_ip,
            "unicast_address": interface_ip, 
            "use_tcp": True, 
            "tcp_host": interface_ip, 
            "tcp_port": 30500, 
            "sd_port": sd_port,
            "sd_address": sd_addr,
            "socket_path": "someipyd.sock" if os.name == 'nt' else "/tmp/someipyd.sock"
        }))
        
    await someipyd.async_main()

if __name__ == "__main__":
    try:
        # Ensure common_ids is importable
        sys.path.append(os.path.dirname(__file__))
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
