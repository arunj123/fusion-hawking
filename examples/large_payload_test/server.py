import logging
import asyncio
import argparse
import sys
import os
import signal

# Add src/python to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../src/python'))

from fusion_hawking.runtime import SomeIpRuntime, LogLevel, RequestHandler

SERVICE_ID = 0x5000
METHOD_ID_GET = 0x0001
METHOD_ID_ECHO = 0x0002
INSTANCE_ID = 1

# 5KB Payload (Segments: ~4)
LARGE_PAYLOAD_SIZE = 5000 

class LargePayloadService(RequestHandler):
    def get_service_id(self) -> int:
        return SERVICE_ID

    def handle(self, header: dict, payload: bytes) -> bytes:
        mid = header.get("method_id")
        client_addr = "unknown" # header doesn't pass addr? handle signature is (header, payload)
        
        if mid == METHOD_ID_GET:
            print(f"Received GET Request for {LARGE_PAYLOAD_SIZE} bytes")
            # Generate deterministic large payload
            data = bytearray([i % 256 for i in range(LARGE_PAYLOAD_SIZE)])
            return (0, data)
            
        elif mid == METHOD_ID_ECHO:
            print(f"Received ECHO Request, size={len(payload)}")
            if len(payload) != LARGE_PAYLOAD_SIZE:
                 print(f"WARNING: Received size {len(payload)} != Expected {LARGE_PAYLOAD_SIZE}")
            return (0, payload)
            
        return (0x03, b"") # E_UNKNOWN_METHOD

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config_tp.json")
    args = parser.parse_args()
    
    runtime = SomeIpRuntime(config_path=args.config, instance_name="tp_server")
    
    service = LargePayloadService()
    runtime.offer_service("tp_service", service)
    
    runtime.start()
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        runtime.stop()

if __name__ == "__main__":
    asyncio.run(main())
