import unittest
import sys
import os
import struct
import socket

# Add build/generated/python and src/python to path
sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))

from runtime import SomeIpRuntime, MathServiceStub, MathServiceClient

class MockSocket:
    def __init__(self):
        self.sent = []
        self.bound_port = 0
    
    def bind(self, addr):
        self.bound_port = addr[1]
        
    def getsockname(self):
        return ('0.0.0.0', self.bound_port)
        
    def sendto(self, data, addr):
        self.sent.append((data, addr))
        
    def setsockopt(self, *args): pass
    def setblocking(self, *args): pass

class TestPythonRuntime(unittest.TestCase):
    def setUp(self):
        # We need to monkeypath socket to avoid real networking in unit tests
        self.original_socket = socket.socket
        # socket.socket = lambda *args, **kwargs: MockSocket() 
        # Doing this globally is risky if other tests run. 
        # But SomeIpRuntime creates sockets in __init__.
        # For simplicity in this environment, let's just instantiate runtime.
        # It binds to port 0 (random), so it shouldn't conflict.
        
        # Use relative path to test config
        config_path = os.path.join(os.getcwd(), 'tests', 'test_config.json')
        self.runtime = SomeIpRuntime(config_path, "test_instance")
        self.runtime.start()

    def tearDown(self):
        self.runtime.stop()

    def test_offer_service(self):
        stub = MathServiceStub()
        self.runtime.offer_service("math-service", stub)
        self.assertIn(stub.SERVICE_ID, self.runtime.services)
        
    def test_get_client(self):
        # Inject service discovery
        self.runtime.remote_services[4097] = ('127.0.0.1', 12345)
        client = self.runtime.get_client("math-client", MathServiceClient)
        self.assertIsInstance(client, MathServiceClient)
        self.assertEqual(client.runtime, self.runtime)

if __name__ == '__main__':
    unittest.main()
