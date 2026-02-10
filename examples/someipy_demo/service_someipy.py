import asyncio
import logging
import sys
import os
import socket
import struct
import platform
from typing import Tuple

# Add someipy to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../third_party/someipy/src")))

# Monkey-patch someipy for Windows support
import someipy._internal.utils as someipy_utils

def patched_create_rcv_multicast_socket(ip_address: str, port: int, interface_address: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if os.name == 'nt':
        sock.bind(("", port))
    else:
        sock.bind((ip_address, port))
    mreq = struct.pack("4s4s", socket.inet_aton(ip_address), socket.inet_aton(interface_address))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock

someipy_utils.create_rcv_multicast_socket = patched_create_rcv_multicast_socket

from someipy import (
    TransportLayerProtocol,
    MethodResult,
    ReturnCode,
    MessageType,
    connect_to_someipy_daemon,
    ServerServiceInstance,
    ServiceBuilder,
    Method,
)
from someipy.someipy_logging import set_someipy_log_level

# Import shared IDs
try:
    from common_ids import SOMEIPY_SERVICE_ID, SOMEIPY_INSTANCE_ID, SOMEIPY_METHOD_ECHO
except ImportError:
    # Handle running from different context
    sys.path.append(os.path.dirname(__file__))
    from common_ids import SOMEIPY_SERVICE_ID, SOMEIPY_INSTANCE_ID, SOMEIPY_METHOD_ECHO

DEFAULT_INTERFACE_IP = "127.0.0.1"
SERVICE_ID = SOMEIPY_SERVICE_ID
INSTANCE_ID = SOMEIPY_INSTANCE_ID
METHOD_ID = SOMEIPY_METHOD_ECHO

async def echo_handler(input_data: bytes, addr: Tuple[str, int]) -> MethodResult:
    print(f"[someipy Service] Received {len(input_data)} bytes from {addr}")
    
    result = MethodResult()
    result.message_type = MessageType.RESPONSE
    result.return_code = ReturnCode.E_OK
    result.payload = input_data # Just echo back
    
    return result

async def main():
    set_someipy_log_level(logging.INFO)
    
    interface_ip = DEFAULT_INTERFACE_IP
    if "--interface_ip" in sys.argv:
        idx = sys.argv.index("--interface_ip")
        if idx + 1 < len(sys.argv):
            interface_ip = sys.argv[idx+1]

    print(f"[someipy Service] Connecting to daemon on {interface_ip}...")
    try:
        # For Windows, we might need to specify TCP if the daemon is on WSL or another process
        # someipy defaults to UNIX domain sockets on Linux, but uses TCP/IP on Windows for daemon comms
        if os.name == 'nt':
             someipy_daemon = await connect_to_someipy_daemon(
                {"use_tcp": True, "tcp_host": interface_ip, "tcp_port": 30500}
            )
        else:
            someipy_daemon = await connect_to_someipy_daemon()
    except Exception as e:
        print(f"[someipy Service] Failed to connect to daemon: {e}")
        print("[someipy Service] Make sure someipyd.py is running!")
        return

    echo_method = Method(
        id=METHOD_ID,
        protocol=TransportLayerProtocol.UDP,
        method_handler=echo_handler,
    )

    service = (
        ServiceBuilder()
        .with_service_id(SERVICE_ID)
        .with_major_version(1)
        .with_method(echo_method)
        .build()
    )

    service_instance = ServerServiceInstance(
        daemon=someipy_daemon,
        service=service,
        instance_id=INSTANCE_ID,
        endpoint_ip=interface_ip,
        endpoint_port=30001,
        ttl=5,
        cyclic_offer_delay_ms=2000,
    )

    print(f"[someipy Service] Offering Service 0x{SERVICE_ID:04x}:0x{INSTANCE_ID:04x} on {interface_ip}:30001")
    await service_instance.start_offer()

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("[someipy Service] Stopping...")
        await service_instance.stop_offer()
    finally:
        await someipy_daemon.disconnect_from_daemon()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
