"""
Virtual Network Service Discovery Test (Host-Veth-Bridge Topology)

Tests SOME/IP Service Discovery across virtual interfaces (veth pairs connected to br0).
Requires: Linux with iproute2, setup_vnet.sh run beforehand.
"""

import subprocess
import sys
import os
import time
import json
import pytest
import socket
import struct

# Check if VNet interfaces exist on Host
def _check_vnet_available():
    """Check if virtual network interfaces are set up."""
    if sys.platform != "linux": return False
    try:
        # Check for veth_ns_ecu1 (Host side interface)
        r = subprocess.run(['ip', 'link', 'show', 'veth_ns_ecu1'], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False

pytestmark = [
    pytest.mark.skipif(
        not _check_vnet_available(),
        reason="Requires VNet setup (run tools/fusion/scripts/setup_vnet.sh)"
    ),
]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PYTHON_RUNTIME = os.path.join(PROJECT_ROOT, 'src', 'python')

# Map logical names to Host Interfaces and IPs
VNET_CONFIG = {
    "ns_ecu1": {"iface": "veth_ns_ecu1", "ip": "10.0.1.1"},
    "ns_ecu2": {"iface": "veth_ns_ecu2", "ip": "10.0.1.2"},
    "ns_ecu3": {"iface": "veth_ns_ecu3", "ip": "10.0.1.3"}
}

def _ping_interface(src_iface, target_ip):
    """Ping target IP using specific source interface."""
    cmd = ['ping', '-I', src_iface, '-c', '1', '-W', '1', target_ip]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

class TestVnetConnectivity:
    """Basic virtual network connectivity tests."""

    def test_veth_interfaces_exist(self):
        """Verify host interfaces exist."""
        r = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True)
        for name in VNET_CONFIG.keys():
            iface = VNET_CONFIG[name]["iface"]
            assert iface in r.stdout, f"Interface {iface} missing"

    def test_ecu1_to_ecu2_connectivity(self):
        """Verify connectivity between VNet IPs via Bridge."""
        # Ping 10.0.1.2 from veth_ns_ecu1
        # Note: Since they are on the same bridge/network stack, local routing might shortcut,
        # but forcing interface ensures we use the topology.
        assert _ping_interface(VNET_CONFIG["ns_ecu1"]["iface"], VNET_CONFIG["ns_ecu2"]["ip"])

    def test_ecu1_to_ecu3_connectivity(self):
        assert _ping_interface(VNET_CONFIG["ns_ecu1"]["iface"], VNET_CONFIG["ns_ecu3"]["ip"])

    def test_ecu2_to_ecu3_connectivity(self):
        assert _ping_interface(VNET_CONFIG["ns_ecu2"]["iface"], VNET_CONFIG["ns_ecu3"]["ip"])


class TestVnetMulticast:
    """Multicast routing tests across VNet interfaces."""

    def test_multicast_interface_enabled(self):
        """Verify multicast is enabled on veth interfaces."""
        for name in VNET_CONFIG.keys():
            iface = VNET_CONFIG[name]["iface"]
            r = subprocess.run(['ip', 'link', 'show', iface], capture_output=True, text=True)
            assert 'MULTICAST' in r.stdout, f"Multicast not enabled on {iface}"

    def test_multicast_udp_delivery(self):
        """Test that a multicast UDP packet sent from ecu1 is received by ecu2."""
        MCAST_GROUP = '224.224.224.245'
        PORT = 30491 # Use different port than SD to avoid conflict
        
        RECEIVER_IP = VNET_CONFIG["ns_ecu2"]["ip"]
        SENDER_IP = VNET_CONFIG["ns_ecu1"]["ip"]
        SENDER_IFACE = VNET_CONFIG["ns_ecu1"]["iface"]

        # Receiver (binds to ANY or specific IP, joins group)
        # We bind to the specific VNet IP to ensure isolation test validity
        listener_script = (
            f"import socket, struct, sys, time; "
            f"s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP); "
            f"s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
            f"s.bind(('{RECEIVER_IP}', {PORT})); " # Bind to specific VNet IP
            f"mreq = struct.pack('4s4s', socket.inet_aton('{MCAST_GROUP}'), socket.inet_aton('{RECEIVER_IP}')); "
            f"s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq); "
            f"s.settimeout(5); "
            f"print('LISTENING'); "
            f"sys.stdout.flush(); "
            f"try:\n"
            f"    data, addr = s.recvfrom(1024)\n"
            f"    print(f'RECEIVED:{{data.decode()}}:FROM:{{addr[0]}}')\n"
            f"except Exception as e:\n"
            f"    print(f'ERROR: {{e}}')\n"
            f"    sys.exit(1)"
        )

        listener = subprocess.Popen(
            [sys.executable, '-u', '-c', listener_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        # Wait for listener to start
        start = time.time()
        while time.time() - start < 5:
            if listener.poll() is not None: break
            line = listener.stdout.readline()
            if "LISTENING" in line: break
        
        # Sender (from ecu1 IP)
        sender_script = (
            f"import socket; "
            f"s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); "
            f"s.bind(('{SENDER_IP}', 0)); " # Bind source IP
            f"s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('{SENDER_IP}')); "
            # Set TTL to ensure it crosses bridge if needed (though local)
            f"s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2); " 
            f"s.sendto(b'VNET_TEST_MSG', ('{MCAST_GROUP}', {PORT})); "
            f"s.close()"
        )

        subprocess.run([sys.executable, '-c', sender_script], check=True)

        try:
            stdout, stderr = listener.communicate(timeout=5)
            assert 'RECEIVED:VNET_TEST_MSG' in stdout, f"Receiver failed: {stdout} {stderr}"
            # Verify source IP is indeed preserved/routed correctly
            assert f'FROM:{SENDER_IP}' in stdout
        except subprocess.TimeoutExpired:
            listener.kill()
            pytest.fail("Multicast listener timed out")
