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
        r = subprocess.run(['ip', 'link', 'show', 'veth_ns_ecu1_h0'], capture_output=True, text=True, timeout=5)
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
    "ns_ecu1": {"iface": "veth_ns_ecu1_h0", "ip": "10.0.1.1"},
    "ns_ecu2": {"iface": "veth_ns_ecu2_h0", "ip": "10.0.1.2"},
    "ns_ecu3": {"iface": "veth_ns_ecu3_h0", "ip": "10.0.1.3"}
}

def _ping_between_ns(src_ns, target_ip):
    """Ping target IP from inside a source namespace."""
    cmd = ['sudo', 'ip', 'netns', 'exec', src_ns, 'ping', '-c', '1', '-W', '1', target_ip]
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
        """Verify connectivity between namespaces via Bridge."""
        assert _ping_between_ns("ns_ecu1", VNET_CONFIG["ns_ecu2"]["ip"])

    def test_ecu1_to_ecu3_connectivity(self):
        assert _ping_between_ns("ns_ecu1", VNET_CONFIG["ns_ecu3"]["ip"])

    def test_ecu2_to_ecu3_connectivity(self):
        assert _ping_between_ns("ns_ecu2", VNET_CONFIG["ns_ecu3"]["ip"])


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

        import textwrap
        listener_script = textwrap.dedent(f"""
            import socket, struct, sys, time
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', {PORT}))
            mreq = struct.pack('4s4s', socket.inet_aton('{MCAST_GROUP}'), socket.inet_aton('{RECEIVER_IP}'))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.settimeout(5)
            print('LISTENING')
            sys.stdout.flush()
            try:
                data, addr = s.recvfrom(1024)
                print(f'RECEIVED:{{data.decode()}}:FROM:{{addr[0]}}')
            except Exception as e:
                print(f'ERROR: {{e}}')
                sys.exit(1)
        """)

        listener = subprocess.Popen(
            ['sudo', 'ip', 'netns', 'exec', 'ns_ecu2', sys.executable, '-u', '-c', listener_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        # Wait for listener to start
        start = time.time()
        while time.time() - start < 5:
            if listener.poll() is not None: break
            line = listener.stdout.readline()
            if "LISTENING" in line: break
        
        # Sender (from ecu1 IP)
        sender_script = textwrap.dedent(f"""
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(('{SENDER_IP}', 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('{SENDER_IP}'))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.sendto(b'VNET_TEST_MSG', ('{MCAST_GROUP}', {PORT}))
            s.close()
        """)

        subprocess.run(['sudo', 'ip', 'netns', 'exec', 'ns_ecu1', sys.executable, '-c', sender_script], check=True)

        try:
            stdout, stderr = listener.communicate(timeout=5)
            assert 'RECEIVED:VNET_TEST_MSG' in stdout, f"Receiver failed: {stdout} {stderr}"
            # Verify source IP is indeed preserved/routed correctly
            assert f'FROM:{SENDER_IP}' in stdout
        except subprocess.TimeoutExpired:
            listener.kill()
            pytest.fail("Multicast listener timed out")
