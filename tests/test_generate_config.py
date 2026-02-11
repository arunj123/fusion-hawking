
import unittest
import os
import json
import shutil
import tempfile
import subprocess
import sys

class TestGenerateConfig(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory
        self.test_dir = tempfile.mkdtemp()
        self.examples_dir = os.path.join(self.test_dir, 'examples')
        os.makedirs(self.examples_dir)
        
        # Path to the script under test
        self.script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tools', 'generate_config.py'))
        
        # Create dummy interface.py
        self.interface_py = os.path.join(self.examples_dir, 'interface.py')
        with open(self.interface_py, 'w') as f:
            f.write("""
class MathService:
    is_service = True
    service_id = 9991

class StringService:
    is_service = True
    service_id = 9992

class OtherClass:
    pass
""")

        # Create dummy config.json
        self.config_json = os.path.join(self.examples_dir, 'config.json')
        self.initial_config = {
            "instances": {
                "inst1": {
                    "providing": {
                        "math-service": {
                            "service_id": 0,
                            "endpoint": "ep1"
                        },
                        "string-client": { # Alias matches mapped name for StringService
                            "service_id": 0,
                            "endpoint": "ep2"
                        }
                    }
                }
            }
        }
        with open(self.config_json, 'w') as f:
            json.dump(self.initial_config, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_generate_update(self):
        # Run the script with CWD = self.test_dir
        # It expects 'examples/interface.py` and `examples/config.json` relative to CWD
        
        result = subprocess.run(
            [sys.executable, self.script_path],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        
        self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
        self.assertIn("Configuration updated successfully", result.stdout)
        
        # Verify config.json was updated
        with open(self.config_json, 'r') as f:
            new_config = json.load(f)
            
        math_svc = new_config["instances"]["inst1"]["providing"]["math-service"]
        self.assertEqual(math_svc["service_id"], 9991)
        
        str_svc = new_config["instances"]["inst1"]["providing"]["string-client"]
        self.assertEqual(str_svc["service_id"], 9992)

if __name__ == '__main__':
    unittest.main()
