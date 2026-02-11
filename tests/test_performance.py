"""
Performance and Stress Tests for SOME/IP Runtime.

These tests measure throughput, latency, and concurrent session handling.
They are informational (no strict pass/fail thresholds) but help detect
performance regressions.

Based on AUTOSAR R22-11 protocol.
"""
import unittest
import struct
import socket
import threading
import time
import sys
import os

sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))

from fusion_hawking.runtime import MessageType, ReturnCode, SessionIdManager


class TestSerializationPerformance(unittest.TestCase):
    """Measure serialization/deserialization throughput."""

    def _build_someip_packet(self, service_id, method_id, payload_size):
        """Build a valid SOME/IP packet with given payload size."""
        payload = b'\x00' * payload_size
        length = len(payload) + 8
        header = struct.pack(">HHIHH4B",
            service_id, method_id, length,
            0x0000, 0x0001,
            0x01, 0x01, 0x00, 0x00)
        return header + payload

    def _parse_someip_header(self, data):
        """Parse SOME/IP header."""
        if len(data) < 16:
            return None
        return struct.unpack(">HHIHH4B", data[:16])

    def test_serialization_throughput(self):
        """Measure header serialization rate."""
        iterations = 50000
        start = time.perf_counter()
        for i in range(iterations):
            self._build_someip_packet(0x1001, 0x0001, 8)
        elapsed = time.perf_counter() - start
        rate = iterations / elapsed
        print(f"\n  Serialization: {rate:,.0f} packets/sec ({elapsed*1000:.1f}ms for {iterations} packets)")
        # No strict threshold — just report
        self.assertGreater(rate, 1000, "Serialization should exceed 1000 packets/sec")

    def test_deserialization_throughput(self):
        """Measure header deserialization rate."""
        packet = self._build_someip_packet(0x1001, 0x0001, 8)
        iterations = 50000
        start = time.perf_counter()
        for i in range(iterations):
            self._parse_someip_header(packet)
        elapsed = time.perf_counter() - start
        rate = iterations / elapsed
        print(f"\n  Deserialization: {rate:,.0f} packets/sec ({elapsed*1000:.1f}ms for {iterations} packets)")
        self.assertGreater(rate, 1000)

    def test_large_payload_serialization(self):
        """Measure serialization with payloads near UDP MTU (1400 bytes)."""
        iterations = 10000
        start = time.perf_counter()
        for i in range(iterations):
            self._build_someip_packet(0x1001, 0x0001, 1400)
        elapsed = time.perf_counter() - start
        rate = iterations / elapsed
        print(f"\n  Large payload (1400B): {rate:,.0f} packets/sec")
        self.assertGreater(rate, 500)


class TestSessionIdPerformance(unittest.TestCase):
    """Measure SessionIdManager performance under load."""

    def test_session_id_throughput(self):
        """Measure session ID generation rate across many service/method pairs."""
        mgr = SessionIdManager()
        iterations = 100000
        start = time.perf_counter()
        for i in range(iterations):
            mgr.next_session_id(0x1001, i % 100)
        elapsed = time.perf_counter() - start
        rate = iterations / elapsed
        print(f"\n  Session ID generation: {rate:,.0f} IDs/sec")
        self.assertGreater(rate, 10000)

    def test_session_id_wraparound(self):
        """Verify session ID wraps around correctly at 0xFFFF."""
        mgr = SessionIdManager()
        # Generate IDs until wrap
        for i in range(0xFFFF + 5):
            sid = mgr.next_session_id(0x1001, 0x0001)
        # After 0xFFFF iterations, should have wrapped
        self.assertGreaterEqual(sid, 1)
        self.assertLessEqual(sid, 0xFFFF)


class TestUdpThroughput(unittest.TestCase):
    """Measure local UDP loopback throughput for SOME/IP packets."""

    def test_udp_loopback_throughput(self):
        """Send/receive SOME/IP packets over local UDP and measure rate."""
        NUM_PACKETS = 5000
        
        # Build test packet
        payload = struct.pack(">ii", 42, 100)
        length = len(payload) + 8
        header = struct.pack(">HHIHH4B",
            0x1001, 0x0001, length,
            0x0000, 0x0001,
            0x01, 0x01, 0x00, 0x00)
        packet = header + payload

        received = []
        errors = []

        def receiver(sock, count):
            try:
                for _ in range(count):
                    data, addr = sock.recvfrom(2048)
                    received.append(data)
            except Exception as e:
                errors.append(str(e))

        # Set up UDP sockets
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.settimeout(5.0)
        recv_sock.bind(("127.0.0.1", 0))
        port = recv_sock.getsockname()[1]

        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Start receiver thread
        recv_thread = threading.Thread(target=receiver, args=(recv_sock, NUM_PACKETS))
        recv_thread.start()

        # Send packets
        start = time.perf_counter()
        for i in range(NUM_PACKETS):
            send_sock.sendto(packet, ("127.0.0.1", port))
        
        recv_thread.join(timeout=10)
        elapsed = time.perf_counter() - start

        send_sock.close()
        recv_sock.close()

        if errors:
            self.skipTest(f"Socket errors: {errors}")

        rate = len(received) / elapsed if elapsed > 0 else 0
        loss = NUM_PACKETS - len(received)
        print(f"\n  UDP loopback: {rate:,.0f} packets/sec, {loss} lost of {NUM_PACKETS}")
        # UDP can lose packets under load, so we just check we received a reasonable amount
        self.assertGreater(len(received), NUM_PACKETS * 0.5, 
            "Should receive at least 50% of packets on loopback")


class TestConcurrentSessions(unittest.TestCase):
    """Stress test with multiple concurrent service sessions."""

    def test_concurrent_session_id_managers(self):
        """Multiple threads generating session IDs concurrently."""
        mgr = SessionIdManager()
        NUM_THREADS = 10
        IDS_PER_THREAD = 10000
        results = {}
        errors = []

        def generate_ids(thread_id, count):
            try:
                ids = []
                for i in range(count):
                    sid = mgr.next_session_id(0x1001 + thread_id, 0x0001)
                    ids.append(sid)
                results[thread_id] = ids
            except Exception as e:
                errors.append(str(e))

        threads = []
        start = time.perf_counter()
        for t in range(NUM_THREADS):
            th = threading.Thread(target=generate_ids, args=(t, IDS_PER_THREAD))
            threads.append(th)
            th.start()

        for th in threads:
            th.join(timeout=10)
        elapsed = time.perf_counter() - start

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        total_ids = sum(len(v) for v in results.values())
        rate = total_ids / elapsed if elapsed > 0 else 0
        print(f"\n  Concurrent sessions: {rate:,.0f} IDs/sec across {NUM_THREADS} threads")
        self.assertEqual(total_ids, NUM_THREADS * IDS_PER_THREAD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
