import unittest
import sys
import os
import struct

# Standard path setup
PROJECT_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src', 'python'))
# Add per-project generated bindings path
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'build', 'generated', 'integrated_apps', 'python'))

from fusion_hawking.runtime import SomeIpRuntime

# Try importing generated bindings
try:
    from bindings import SensorServiceOnValueChangedEvent
except ImportError:
    SensorServiceOnValueChangedEvent = None

class TestEvents(unittest.TestCase):
    def setUp(self):
        if SensorServiceOnValueChangedEvent is None:
            self.skipTest("Generated bindings not found in build/generated/integrated_apps/python")
        self.runtime = SomeIpRuntime(None, "test", None)

    def test_event_serialization(self):
        """Verify that generated event classes can serialize/deserialize correctly."""
        evt = SensorServiceOnValueChangedEvent(value=25.5)
        data = evt.serialize()
        # Float 25.5 is 0x41cc0000 (IEEE 754)
        # Serialized structure for SensorServiceOnValueChangedEvent:
        # >f (float)
        expected_hex = "41cc0000"
        self.assertEqual(data.hex(), expected_hex)
        
        evt2 = SensorServiceOnValueChangedEvent.deserialize(data)
        self.assertAlmostEqual(evt2.value, 25.5)

    def test_event_subscription(self):
        """Verify that Python Runtime can subscribe/unsubscribe to eventgroups."""
        SERVICE_ID = 0x5000 # SensorService
        EVENTGROUP_ID = 0x8001
        INSTANCE_ID = 1
        
        # Subscribe
        self.runtime.subscribe_eventgroup(SERVICE_ID, INSTANCE_ID, EVENTGROUP_ID)
        self.assertTrue(self.runtime.subscriptions.get((SERVICE_ID, EVENTGROUP_ID)))
        
        # Unsubscribe
        self.runtime.unsubscribe_eventgroup(SERVICE_ID, INSTANCE_ID, EVENTGROUP_ID)
        self.assertFalse(self.runtime.subscriptions.get((SERVICE_ID, EVENTGROUP_ID)))

if __name__ == "__main__":
    unittest.main()
