import asyncio
import json
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
from someipy_patch import apply_patch
apply_patch()

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
    config_path = None
    
    # Check for Fusion config (positional or --config)
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        config_path = sys.argv[1]
    elif "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx+1]
            
    if config_path:
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
                # Try to extract IP from instances (PythonService)
                if "instances" in cfg and "PythonService" in cfg["instances"]:
                    inst = cfg["instances"]["PythonService"]
                    bind_key = inst.get("unicast_bind", {}).get("primary")
                    if bind_key and "interfaces" in cfg:
                        iface = cfg["interfaces"].get("primary")
                        if iface and bind_key in iface["endpoints"]:
                             interface_ip = iface["endpoints"][bind_key]["ip"]
                             print(f"[someipy Service] Resolved IP from PythonService config: {interface_ip}")
                elif "interfaces" in cfg:
                    # Fallback to primary iface IP
                    iface = cfg["interfaces"].get("primary") or next(iter(cfg["interfaces"].values()))
                    # find first non-mcast endpoint
                    for ep in iface["endpoints"].values():
                        if not ep.get("ip", "").startswith("224.") and not ep.get("ip", "").startswith("ff"):
                            interface_ip = ep["ip"]
                            print(f"[someipy Service] Resolved IP from primary interface: {interface_ip}")
                            break
        except Exception as e:
            print(f"[someipy Service] Error reading config {config_path}: {e}")

    if "--interface_ip" in sys.argv:
        idx = sys.argv.index("--interface_ip")
        if idx + 1 < len(sys.argv):
            interface_ip = sys.argv[idx+1]

    print(f"[someipy Service] Connecting to daemon on {interface_ip}...")
    someipy_daemon = None
    retries = 10
    while retries > 0:
        try:
            # Always use TCP to connect to the daemon since start_daemon.py starts with use_tcp=True
            someipy_daemon = await connect_to_someipy_daemon(
                {"use_tcp": True, "tcp_host": interface_ip, "tcp_port": 30500}
            )
            break
        except Exception as e:
            retries -= 1
            if retries == 0:
                print(f"[someipy Service] Failed to connect to daemon after multiple retries: {e}")
                print("[someipy Service] Make sure someipyd.py is running!")
                return
            print(f"[someipy Service] Daemon not ready yet, retrying in 2s... ({retries} left)")
            await asyncio.sleep(2)

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
    import traceback
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        sys.exit(1)
