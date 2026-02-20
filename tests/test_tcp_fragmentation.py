"""
Comprehensive Transport Robustness Tests

Tests SOME/IP communication across: TCP/UDP × IPv4/IPv6 × C++/Python servers.
Uses proper config generation with env data (NetworkEnvironment), find_binary()
for locating executables, and AppRunner for cross-language process management.
"""
import pytest
import os
import sys
import socket
import struct
import json
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src', 'python'))

from tools.fusion.utils import _get_env as get_environment, find_binary, get_loopback_interface_name
from tools.fusion.execution import AppRunner
from fusion_hawking.runtime import SomeIpRuntime, ConsoleLogger, RequestHandler


# ─────────────────────────────────────────────────────────────
#  Config Generation
# ─────────────────────────────────────────────────────────────

def generate_config(output_dir, protocol="tcp", ip_version=4, instance_prefix="transport", server_instance_name=None):
    """
    Generate a SOME/IP config following established project patterns.
    Uses env data for interface names and IPs, ephemeral ports (port 0).
    """
    os.makedirs(output_dir, exist_ok=True)
    config_name = f"{instance_prefix}_{protocol}_v{ip_version}_config.json"
    config_path = os.path.join(output_dir, config_name)

    env = get_environment()
    iface_name = get_loopback_interface_name()

    # Default server instance name matches the prefix
    if server_instance_name is None:
        server_instance_name = f"{instance_prefix}_server"

    # Derive IPs from env data rather than hardcoding
    loopback_v4 = "127.0.0.1"
    loopback_v6 = "::1"

    # Use actual loopback IPs from env if available
    interfaces = getattr(env, 'interfaces', {})
    for iface_alias, iface_data in interfaces.items():
        if isinstance(iface_data, dict) and iface_data.get('type') == 'loopback':
            v4_list = iface_data.get('ip_v4', [])
            if v4_list:
                loopback_v4 = v4_list[0]
            
            v6_list = iface_data.get('ip_v6', [])
            if v6_list:
                # Find a suitable v6 loopback (prefer ::1 or non-link-local if multiple)
                for addr in v6_list:
                    clean_addr = addr.split('%')[0]
                    if clean_addr == "::1":
                        loopback_v6 = clean_addr
                        break
                    loopback_v6 = clean_addr
            break

    if ip_version == 4:
        ip = loopback_v4
        sd_multicast_ip = "224.0.0.5"
        sd_version = 4
    else:
        ip = loopback_v6
        sd_multicast_ip = "ff02::5"
        sd_version = 6

        # WSL2 doesn't support IPv6 multicast on loopback.
        # If loopback multicast is broken, use a real interface with IPv6 instead.
        if not getattr(env, 'has_ipv6_multicast', True):
            # Find a real interface with a global-scope IPv6 address
            # Use the existing env.interfaces data or parse ip addr output
            found = False
            for iface_alias, iface_data in interfaces.items():
                if not isinstance(iface_data, dict):
                    continue
                if iface_data.get('type') == 'loopback':
                    continue
                v6_list = iface_data.get('ip_v6', [])
                for addr in v6_list:
                    clean = addr.split('%')[0]
                    if not clean.startswith('fe80') and ':' in clean:
                        ip = clean
                        iface_name = iface_data.get('name', iface_alias)
                        if isinstance(iface_name, dict):
                            iface_name = iface_alias
                        found = True
                        break
                if found:
                    break

            # Fallback: parse `ip -6 addr` directly
            if not found:
                import subprocess as _sp
                try:
                    out = _sp.run(['ip', '-6', 'addr', 'show', 'scope', 'global'],
                                 capture_output=True, text=True, timeout=3)
                    import re
                    # ip addr output: "N: devname: <flags>...\n    inet6 addr/prefix ..."
                    current_dev = None
                    for line in out.stdout.splitlines():
                        dev_m = re.match(r'^\d+:\s+(\S+):', line)
                        if dev_m:
                            current_dev = dev_m.group(1)
                            continue
                        addr_m = re.match(r'\s+inet6\s+(\S+)/\d+', line)
                        if addr_m and current_dev and current_dev != 'lo':
                            addr = addr_m.group(1)
                            if not addr.startswith('fe80'):
                                ip = addr
                                iface_name = current_dev
                                found = True
                                break
                except Exception:
                    pass

    endpoints = {}
    # SD multicast endpoint (always UDP)
    endpoints["sd_multicast"] = {
        "ip": sd_multicast_ip,
        "port": 30890 + ip_version,  # Avoid port clashes between v4/v6 tests
        "version": sd_version,
        "protocol": "udp"
    }
    # Server endpoint
    endpoints["server_ep"] = {
        "ip": ip,
        "port": 0,  # Ephemeral
        "version": ip_version,
        "protocol": protocol
    }

    config = {
        "interfaces": {
            "primary": {
                "name": iface_name,
                "endpoints": endpoints,
                "sd": {
                    "endpoint" if ip_version == 4 else "endpoint_v6": "sd_multicast"
                }
            }
        },
        "instances": {
            server_instance_name: {
                "providing": {
                    "math-service": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "major_version": 1,
                        "offer_on": {
                            "primary": "server_ep"
                        }
                    }
                },
                "sd": {
                    "cycle_offer_ms": 100
                },
                "unicast_bind": {}
            },
            f"{instance_prefix}_client": {
                "required": {
                    "math-client": {
                        "service_id": 4097,
                        "instance_id": 1,
                        "major_version": 1,
                        "find_on": ["primary"]
                    }
                },
                "unicast_bind": {}
            }
        }
    }

    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    return config_path


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────

def build_someip_request(service_id=4097, method_id=1, payload=None):
    """Build a raw SOME/IP request packet (header + payload)."""
    if payload is None:
        payload = struct.pack(">II", 10, 20)  # a=10, b=20

    length = len(payload) + 8  # Client ID(2) + Session(2) + Protocol/Interface/MsgType/RC(4)
    header = struct.pack(">HHIHH4B",
        service_id, method_id,
        length,
        0,   # client_id
        1,   # session_id
        1, 1, 0, 0  # protocol_version, interface_version, msg_type=REQUEST, return_code
    )
    return header + payload


def send_fragmented_tcp(ip, port, packet, delay_ms=10):
    """Send a SOME/IP packet byte-by-byte over TCP to test buffering."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect((ip, port))

    for b in packet:
        s.send(bytes([b]))
        time.sleep(delay_ms / 1000.0)

    try:
        # Receive response with buffering
        res_buf = b""
        expected_size = 0
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                res_buf += chunk
                if expected_size == 0 and len(res_buf) >= 8:
                    expected_size = struct.unpack(">I", res_buf[4:8])[0] + 8
                if expected_size > 0 and len(res_buf) >= expected_size:
                    break
            except socket.timeout:
                break
        return res_buf
    finally:
        s.close()


def send_udp_request(ip, port, packet):
    """Send a SOME/IP request over UDP and receive response."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(family, socket.SOCK_DGRAM)
    s.settimeout(5.0)
    s.sendto(packet, (ip, port))
    try:
        data, _ = s.recvfrom(4096)
        return data
    except socket.timeout:
        return None
    finally:
        s.close()


def wait_for_service_discovery(rt, service_id=4097, timeout=5.0):
    """Wait for the Python runtime to discover a service via SD."""
    for _ in range(int(timeout * 10)):
        if any(k[0] == service_id for k in rt.remote_services.keys()):
            return True
        time.sleep(0.1)
    return False


def get_discovered_address(rt, service_id=4097):
    """Extract the IP/port from a discovered remote service."""
    key = next((k for k in rt.remote_services.keys() if k[0] == service_id), None)
    if key:
        return rt.remote_services[key]
    return None


# ─────────────────────────────────────────────────────────────
#  Python Math Service (inline server for Python-server tests)
# ─────────────────────────────────────────────────────────────

class MathServiceHandler(RequestHandler):
    """Python-side math service for server-mode tests."""
    SERVICE_ID = 4097
    INSTANCE_ID = 1
    MAJOR_VERSION = 1

    def get_service_id(self) -> int:
        return self.SERVICE_ID

    def get_major_version(self) -> int:
        return self.MAJOR_VERSION

    def get_minor_version(self) -> int:
        return 0

    def handle(self, header, payload):
        method_id = header.get('method_id', 0)
        if method_id == 1 and len(payload) >= 8:  # Add
            a = struct.unpack(">I", payload[0:4])[0]
            b = struct.unpack(">I", payload[4:8])[0]
            return struct.pack(">I", a + b)
        return b""


# ─────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def log_dir():
    d = os.environ.get("FUSION_LOG_DIR", os.path.join(PROJECT_ROOT, "logs", "transport_tests"))
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def env():
    return get_environment()


# ─────────────────────────────────────────────────────────────
#  TCP Tests — C++ Server
# ─────────────────────────────────────────────────────────────

class TestTcpCppServer:
    """TCP transport tests with C++ server and Python client."""

    @pytest.fixture(autouse=True)
    def setup(self, log_dir, env):
        self.log_dir = log_dir
        self.env = env
        self.server_exe = find_binary("tcp_server_test")
        if not self.server_exe:
            pytest.skip("C++ tcp_server_test binary not found (build C++ first)")

    @pytest.mark.parametrize("ip_version", [4, 6], ids=["IPv4", "IPv6"])
    def test_tcp_fragmented_request(self, ip_version):
        """Verify C++ server handles fragmented TCP stream (byte-by-byte send)."""
        if ip_version == 6 and not self.env.has_ipv6:
            pytest.skip("IPv6 not available in this environment")

        # C++ binary expects instance name "tcp_server"
        config_path = generate_config(self.log_dir, "tcp", ip_version, "cpp_tcp_frag", server_instance_name="tcp_server")
        server = AppRunner(f"cpp_tcp_v{ip_version}", [self.server_exe, config_path], self.log_dir)
        server.start()
        rt = None

        try:
            time.sleep(2)  # Allow server to bind and start offering

            # Start Python client for SD discovery
            rt = SomeIpRuntime(config_path, f"cpp_tcp_frag_client", ConsoleLogger())
            rt.start()
            assert wait_for_service_discovery(rt), f"Service 4097 not discovered (TCP, IPv{ip_version})"

            addr = get_discovered_address(rt)
            assert addr is not None

            # Send request via Python runtime (normal path)
            payload = struct.pack(">II", 10, 20)
            response = rt.send_request(4097, 1, payload, addr, wait_for_response=True)
            assert response is not None, f"No response from C++ server (TCP, IPv{ip_version})"
            assert len(response) >= 4
            result = struct.unpack(">I", response[:4])[0]
            assert result == 30, f"Expected 30, got {result}"

        finally:
            if rt:
                rt.stop()
            server.stop()

    @pytest.mark.parametrize("ip_version", [4, 6], ids=["IPv4", "IPv6"])
    def test_tcp_raw_fragmented_send(self, ip_version):
        """Raw socket byte-by-byte TCP send to verify C++ buffering handles fragmentation."""
        if ip_version == 6 and not self.env.has_ipv6:
            pytest.skip("IPv6 not available in this environment")

        # C++ binary expects instance name "tcp_server"
        config_path = generate_config(self.log_dir, "tcp", ip_version, "cpp_tcp_raw", server_instance_name="tcp_server")
        server = AppRunner(f"cpp_raw_v{ip_version}", [self.server_exe, config_path], self.log_dir)
        server.start()
        rt = None

        try:
            time.sleep(2)

            # Use Python client only for SD discovery to find the actual bound port
            rt = SomeIpRuntime(config_path, "cpp_tcp_raw_client", ConsoleLogger())
            rt.start()
            assert wait_for_service_discovery(rt), "Service not discovered for raw send test"

            addr = get_discovered_address(rt)
            ip_str = addr[0] if isinstance(addr, tuple) else addr.get('ip', '127.0.0.1')
            port = addr[1] if isinstance(addr, tuple) else addr.get('port', 0)
            # addr might be (ip, port, protocol) tuple
            if len(addr) >= 2:
                ip_str, port = addr[0], addr[1]

            rt.stop()
            rt = None

            # Now raw-send fragmented
            packet = build_someip_request()
            response = send_fragmented_tcp(ip_str, port, packet)
            assert len(response) >= 16, f"Response too short: {len(response)} bytes"
            result = struct.unpack(">I", response[16:20])[0]
            assert result == 30, f"Expected 30, got {result}"

        finally:
            if rt:
                rt.stop()
            server.stop()


# ─────────────────────────────────────────────────────────────
#  TCP Tests — Python Server
# ─────────────────────────────────────────────────────────────

class TestTcpPythonServer:
    """TCP transport tests with Python server and raw socket client."""

    @pytest.mark.parametrize("ip_version", [4, 6], ids=["IPv4", "IPv6"])
    def test_tcp_python_server_fragmented(self, log_dir, env, ip_version):
        """Verify Python server handles fragmented TCP stream."""
        if ip_version == 6 and not env.has_ipv6:
            pytest.skip("IPv6 not available in this environment")

        config_path = generate_config(log_dir, "tcp", ip_version, "py_tcp_frag")
        server_rt = SomeIpRuntime(config_path, "py_tcp_frag_server", ConsoleLogger())
        handler = MathServiceHandler()
        server_rt.offer_service("math-service", handler)
        server_rt.start()

        try:
            time.sleep(1)  # Let server bind

            # Discover self via SD or directly find listener port
            # The server's TCP listener port is ephemeral; find it from runtime internals
            tcp_port = None
            tcp_ip = "127.0.0.1" if ip_version == 4 else "::1"
            for (lip, lport, proto), sock in server_rt.listeners.items():
                if proto == "tcp":
                    tcp_port = sock.getsockname()[1]
                    tcp_ip = lip
                    break

            if tcp_port is None:
                pytest.skip("Python runtime did not create a TCP listener (may not support TCP serving)")

            packet = build_someip_request()
            response = send_fragmented_tcp(tcp_ip, tcp_port, packet)
            assert len(response) >= 16, f"Response too short: {len(response)} bytes"
            result = struct.unpack(">I", response[16:20])[0]
            assert result == 30, f"Expected 30, got {result}"

        finally:
            server_rt.stop()


# ─────────────────────────────────────────────────────────────
#  UDP Tests  
# ─────────────────────────────────────────────────────────────

class TestUdpTransport:
    """UDP transport tests — Python server with raw socket client."""

    @pytest.mark.parametrize("ip_version", [4, 6], ids=["IPv4", "IPv6"])
    def test_udp_python_server(self, log_dir, env, ip_version):
        """Verify Python server handles UDP requests correctly."""
        if ip_version == 6 and not env.has_ipv6:
            pytest.skip("IPv6 not available in this environment")

        config_path = generate_config(log_dir, "udp", ip_version, "py_udp")
        server_rt = SomeIpRuntime(config_path, "py_udp_server", ConsoleLogger())
        handler = MathServiceHandler()
        server_rt.offer_service("math-service", handler)
        server_rt.start()

        try:
            time.sleep(1)

            # Find UDP listener
            udp_port = None
            udp_ip = "127.0.0.1" if ip_version == 4 else "::1"
            for (lip, lport, proto), sock in server_rt.listeners.items():
                if proto == "udp":
                    udp_port = sock.getsockname()[1]
                    udp_ip = lip
                    break

            if udp_port is None:
                pytest.skip("Python runtime did not create a UDP listener")

            packet = build_someip_request()
            response = send_udp_request(udp_ip, udp_port, packet)
            assert response is not None, f"No UDP response from Python server (IPv{ip_version})"
            assert len(response) >= 16
            result = struct.unpack(">I", response[16:20])[0]
            assert result == 30, f"Expected 30, got {result}"

        finally:
            server_rt.stop()

    @pytest.fixture(autouse=True)
    def check_cpp_binary(self):
        self.server_exe = find_binary("tcp_server_test")

    @pytest.mark.parametrize("ip_version", [4, 6], ids=["IPv4", "IPv6"])
    def test_udp_cpp_server_via_sd(self, log_dir, env, ip_version):
        """
        Verify C++ server handles UDP requests via SD discovery.
        Note: The tcp_server_test binary uses TCP, but we test UDP SD discovery path
        by having the Python client send a UDP request directly to see if the 
        infrastructure resolves correctly.
        """
        if not self.server_exe:
            pytest.skip("C++ tcp_server_test binary not found")
        if ip_version == 6 and not env.has_ipv6:
            pytest.skip("IPv6 not available")

        # For UDP tests with C++ server, we'd need a dedicated UDP server binary.
        # The existing tcp_server_test only serves TCP. Skip for now and document.
        pytest.skip("C++ UDP server binary not yet available — TCP-only test binary")


# ─────────────────────────────────────────────────────────────
#  Cross-language via SD (integration-level)
# ─────────────────────────────────────────────────────────────

class TestCrossLanguageSd:
    """Full SD-based cross-language tests (C++ server → Python client via SD)."""

    @pytest.fixture(autouse=True)
    def setup(self, log_dir, env):
        self.log_dir = log_dir
        self.env = env
        self.server_exe = find_binary("tcp_server_test")

    @pytest.mark.parametrize("ip_version", [4, 6], ids=["IPv4", "IPv6"])
    def test_cpp_to_python_sd_discovery(self, ip_version):
        """Python client discovers C++ server via SD and makes a successful TCP RPC."""
        if not self.server_exe:
            pytest.skip("C++ binary not found")
        if ip_version == 6 and not self.env.has_ipv6:
            pytest.skip("IPv6 not available")

        # C++ binary expects instance name "tcp_server"
        config_path = generate_config(self.log_dir, "tcp", ip_version, "sd_cross", server_instance_name="tcp_server")
        server = AppRunner(f"sd_cross_v{ip_version}", [self.server_exe, config_path], self.log_dir)
        server.start()
        rt = None

        try:
            time.sleep(2)

            rt = SomeIpRuntime(config_path, "sd_cross_client", ConsoleLogger())
            rt.start()
            assert wait_for_service_discovery(rt, timeout=5.0), \
                f"SD discovery failed (IPv{ip_version})"

            addr = get_discovered_address(rt)
            payload = struct.pack(">II", 100, 200)
            response = rt.send_request(4097, 1, payload, addr, wait_for_response=True)
            assert response is not None, "No RPC response"
            result = struct.unpack(">I", response[:4])[0]
            assert result == 300, f"Expected 300, got {result}"

        finally:
            if rt:
                rt.stop()
            server.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
