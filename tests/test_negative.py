import pytest
import time
import socket
import struct
import threading
import json
from fusion_hawking.runtime import SomeIpRuntime, MessageType, ReturnCode

# Minimal config for negative testing
CONFIG_JSON = """
{
    "instances": {
        "negative_tester": {
            "unicast_bind": { "primary": "127.0.0.1" },
            "providing": {
                "local_service": {
                    "service_id": 36865, 
                    "instance_id": 1,
                    "major_version": 1,
                    "minor_version": 0,
                    "offer_on": { "primary": "local_ep" }
                }
            },
            "required": {
                "missing_service": {
                    "service_id": 57005,
                    "instance_id": 1
                }
            },
            "interfaces": [ "primary" ]
        },
        "target_instance": {
             "unicast_bind": { "primary": "127.0.0.1" },
             "providing": {},
             "required": {},
             "interfaces": [ "primary" ]
        }
    },
    "interfaces": {
        "primary": {
            "name": "127.0.0.1",
            "endpoints": {
                "local_ep": { "ip": "127.0.0.1", "port": 0, "protocol": "udp", "version": 4 }
            },
            "sd": {
                "endpoint_v4": "local_ep",
                "multicast_hops": 0
            }
        }
    },
    "sd": {
        "cycle_offer_ms": 100,
        "request_timeout_ms": 200
    },
    "endpoints": {}
}
"""
# 36865 = 0x9001
# 57005 = 0xDEAD

@pytest.fixture
def runtime(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(CONFIG_JSON)
    
    rt = SomeIpRuntime(str(config_file), "negative_tester")
    rt.start()
    yield rt
    rt.stop()

def wait_for_service_helper(rt, sid, iid, timeout):
    start = time.time()
    while time.time() - start < timeout:
        if (sid, iid) in rt.remote_services:
            return True
        time.sleep(0.01)
    return False

def test_service_discovery_timeout(runtime):
    """Test that wait_for_service times out for a non-existent service."""
    start_time = time.time()
    found = wait_for_service_helper(runtime, 0xDEAD, 1, timeout=0.3)
    duration = time.time() - start_time
    
    assert found is False
    # Should take at least timeout (0.3s)
    assert duration >= 0.3

def test_request_timeout_unknown_service(runtime):
    """Test that sending a request to an unknown service times out."""
    # We send to a random port
    target = ("127.0.0.1", 54321, "udp")
    
    start_time = time.time()
    # Explicitly verify timeout behavior
    response = runtime.send_request(0xDEAD, 1, b'\x00', target_addr=target, wait_for_response=True, timeout=0.2)
    duration = time.time() - start_time
    
    assert response is None
    assert duration >= 0.2

def test_subscribe_unknown_eventgroup(runtime):
    """Test subscribing to an unknown eventgroup does not crash."""
    # 0xDEAD service, instance 1, eventgroup 99
    try:
        runtime.subscribe_eventgroup(0xDEAD, 1, 99, 1000)
    except Exception as e:
        pytest.fail(f"subscribe_eventgroup raised exception: {e}")
