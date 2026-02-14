import unittest
import os
import json
import tempfile
import shutil
from tools.fusion.utils import patch_configs

class TestUtils(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.test_dir, "examples", "test_app")
        os.makedirs(self.config_dir)
        self.config_path = os.path.join(self.config_dir, "config.json")
        
        # Mock utils.py's known config paths by creating the structure it expects
        # Note: patch_configs heavily hardcodes paths currently, so we might need to mock os.path.join 
        # or temporarily monkeypatch the file list in utils if we want to test arbitrary files.
        # But for now, let's try to monkeypatch the config_paths list in utils if possible, 
        # or just rely on the fact that we can call patch_configs with a root that has the structure.
        
        # Actually patch_configs uses hardcoded relative paths. 
        # Let's see if we can trick it by recreating the specific folder structure it looks for.
        self.real_paths = [
            "examples/integrated_apps/config.json",
            "examples/automotive_pubsub/config.json"
        ]
        
        for p in self.real_paths:
            d = os.path.dirname(os.path.join(self.test_dir, p))
            os.makedirs(d, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_config(self, rel_path, content):
        full_path = os.path.join(self.test_dir, rel_path)
        with open(full_path, 'w') as f:
            json.dump(content, f)
        return full_path

    def read_config(self, rel_path):
        full_path = os.path.join(self.test_dir, rel_path)
        with open(full_path, 'r') as f:
            return json.load(f)

    def test_patch_ipv4(self):
        rel_path = "examples/automotive_pubsub/config.json"
        data = {
            "endpoints": {
                "test_ep": {
                    "ip": "224.0.0.1", # Multicast, should NOT patch
                    "port": 1000
                },
                "unicast_ep": {
                    "ip": "1.2.3.4", # Should patch
                    "port": 2000
                }
            }
        }
        self.create_config(rel_path, data)
        
        # Run patch
        import tools.fusion.utils as utils
        # Mock get_network_info
        original_get_info = utils.get_network_info
        utils.get_network_info = lambda: {'ipv4': '192.168.1.50', 'ipv6': None, 'interface': 'eth99'}
        
        try:
            utils.patch_configs("192.168.1.50", self.test_dir, port_offset=10)
            
            new_data = self.read_config(rel_path)
            self.assertEqual(new_data["endpoints"]["test_ep"]["ip"], "224.0.0.1") # Multicast preserved
            self.assertEqual(new_data["endpoints"]["unicast_ep"]["ip"], "192.168.1.50") # Patched
            self.assertEqual(new_data["endpoints"]["unicast_ep"]["port"], 2010) # Offset applied
            
        finally:
            utils.get_network_info = original_get_info

    def test_patch_ipv6(self):
        rel_path = "examples/automotive_pubsub/config.json"
        data = {
            "endpoints": {
                "ipv6_ep": {
                    "ip": "2001:db8::1",
                    "version": 6
                },
                "ipv4_ep": {
                    "ip": "1.2.3.4"
                }
            }
        }
        self.create_config(rel_path, data)
        
        import tools.fusion.utils as utils
        original_get_info = utils.get_network_info
        utils.get_network_info = lambda: {'ipv4': '192.168.1.50', 'ipv6': 'fe80::1', 'interface': 'eth99'}
        
        try:
            utils.patch_configs("192.168.1.50", self.test_dir)
            
            new_data = self.read_config(rel_path)
            # Should patch IPv6
            self.assertEqual(new_data["endpoints"]["ipv6_ep"]["ip"], "fe80::1")
            # Should patch IPv4
            self.assertEqual(new_data["endpoints"]["ipv4_ep"]["ip"], "192.168.1.50")
            
        finally:
            utils.get_network_info = original_get_info

    def test_patch_loopback_fallback(self):
        rel_path = "examples/automotive_pubsub/config.json"
        data = {
            "endpoints": {
                "ep": {
                    "interface": "eth0",
                    "ip": "1.2.3.4"
                }
            }
        }
        self.create_config(rel_path, data)
        
        import tools.fusion.utils as utils
        original_get_info = utils.get_network_info
        # Mock detection failing (returning None/None) but patch called with 127.0.0.1
        # utils.get_network_info = lambda: {'ipv4': None, 'ipv6': None, 'interface': None} 
        # Actually patch_configs calls get_network_info internally.
        # And usually get_local_ip() would have returned 127.0.0.1 if detection failed.
        # But for test we pass '127.0.0.1' explicitly.
        
        # We need get_network_info to return interface='lo' if it falls back?
        # My change to utils.py makes get_network_info return 'lo' if ipv4 is None/127.
        
        iface_name = 'lo' if os.name != 'nt' else 'Loopback Pseudo-Interface 1'
        utils.get_network_info = lambda: {'ipv4': None, 'ipv6': None, 'interface': iface_name}
        
        try:
            utils.patch_configs("127.0.0.1", self.test_dir)
            
            new_data = self.read_config(rel_path)
            self.assertEqual(new_data["endpoints"]["ep"]["ip"], "127.0.0.1")
            self.assertEqual(new_data["endpoints"]["ep"]["interface"], iface_name)
            
        finally:
            utils.get_network_info = original_get_info

if __name__ == '__main__':
    unittest.main()
