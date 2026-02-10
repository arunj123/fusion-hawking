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
    
    # Load SD port and IP from client_config.json if possible
    sd_port = 30491
    sd_addr = "224.0.0.1"
    try:
        with open("client_config.json", "r") as f:
            cfg = json.load(f)
            sd_port = cfg["endpoints"]["sd_multicast"]["port"]
            sd_addr = cfg["endpoints"]["sd_multicast"]["ip"]
            print(f"[someipy Daemon] Isolated SD: {sd_addr}:{sd_port}")
    except Exception as e:
        print(f"[someipy Daemon] Could not read client_config.json, using defaults: {e}")

    # Import someipyd and run it
    import someipy.someipyd as someipyd
    import json as py_json
    
    # We need to mock sys.argv or pass config
    config_file = "someipyd_config.json"
    sys.argv = [sys.argv[0], "--config", config_file]
    
    # Create a dummy config file with dynamic SD port and address
    with open(config_file, "w") as f:
        f.write(py_json.dumps({
            "unicast_address": "127.0.0.1", 
            "use_tcp": True, 
            "tcp_host": "127.0.0.1", 
            "tcp_port": 30500, 
            "sd_port": sd_port,
            "sd_address": sd_addr
        }))
        
    await someipyd.async_main()

if __name__ == "__main__":
    try:
        # Ensure common_ids is importable
        sys.path.append(os.path.dirname(__file__))
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
