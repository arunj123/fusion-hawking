
import unittest
from tools.fusion.config_validator import validate_config

class TestConfigValidator(unittest.TestCase):
    def setUp(self):
        self.valid_config = {
            "endpoints": {
                "test_ep": {
                    "ip": "127.0.0.1",
                    "interface": "lo",
                    "port": 12345,
                    "protocol": "udp",
                    "version": 4
                }
            },
            "instances": {
                "test_inst": {
                    "providing": {
                        "test_svc": {
                            "service_id": 100,
                            "instance_id": 1,
                            "endpoint": "test_ep"
                        }
                    },
                    "required": {},
                    "sd": {}
                }
            }
        }

    def test_valid_config(self):
        errors = validate_config(self.valid_config)
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_missing_required_field(self):
        # Remove 'ip' from endpoint
        del self.valid_config["endpoints"]["test_ep"]["ip"]
        errors = validate_config(self.valid_config)
        self.assertTrue(any("Missing required field 'ip'" in e for e in errors))

    def test_invalid_type(self):
        # Set port to string
        self.valid_config["endpoints"]["test_ep"]["port"] = "12345"
        errors = validate_config(self.valid_config)
        self.assertTrue(any("Expected integer" in e for e in errors))

    def test_invalid_ip(self):
        self.valid_config["endpoints"]["test_ep"]["ip"] = "999.999.999.999"
        errors = validate_config(self.valid_config)
        self.assertTrue(any("invalid IP" in e for e in errors))

    def test_duplicate_service(self):
        # Add another instance providing same service
        self.valid_config["instances"]["inst2"] = {
            "providing": {
                "test_svc_dup": {
                    "service_id": 100, 
                    "instance_id": 1,
                    "endpoint": "test_ep"
                }
            }
        }
        errors = validate_config(self.valid_config)
        self.assertTrue(any("Duplicate Service" in e for e in errors))

    def test_unknown_endpoint(self):
        self.valid_config["instances"]["test_inst"]["providing"]["test_svc"]["endpoint"] = "missing_ep"
        errors = validate_config(self.valid_config)
        self.assertTrue(any("references unknown endpoint" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
