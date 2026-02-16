"""
Automotive Pub-Sub Demo: ADAS Application (Python)

This application subscribes to FusionService events and processes
fused track data for ADAS warnings (collision warning, etc.).

Pattern: Pure Subscriber - receives events, no service offering.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Fusion Hawking Contributors
"""
import sys
import os
import time

# Path setup
# In the test environment, PYTHONPATH is set. We only add relative paths for local dev.
if os.path.exists(os.path.join(os.getcwd(), 'src', 'python')):
    sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'python'))
if os.path.exists(os.path.join(os.getcwd(), 'build', 'generated', 'python')):
    sys.path.insert(0, os.path.join(os.getcwd(), 'build', 'generated', 'python'))

from fusion_hawking import SomeIpRuntime, LogLevel, ConsoleLogger


# Mock FusedTrack for demo purposes (would normally be generated)
class FusedTrack:
    def __init__(self, track_id=0, position_x=0.0, position_y=0.0, 
                 velocity_x=0.0, velocity_y=0.0, confidence=0.0):
        self.track_id = track_id
        self.position_x = position_x
        self.position_y = position_y
        self.velocity_x = velocity_x
        self.velocity_y = velocity_y
        self.confidence = confidence


class AdasApplication:
    """ADAS Application - subscribes to fusion tracks and generates warnings."""
    
    def __init__(self, runtime):
        self.runtime = runtime
        self.logger = runtime.logger
        self.track_count = 0
        self.warning_distance = 10.0  # meters
        
    def on_track_update(self, tracks):
        """Handle incoming fused track updates."""
        self.track_count += len(tracks)
        
        self.logger.log(
            LogLevel.INFO,
            "ADAS",
            f"Received {len(tracks)} fused tracks (total: {self.track_count})"
        )
        
        # Check for collision warnings
        for track in tracks:
            distance = (track.position_x**2 + track.position_y**2)**0.5
            if distance < self.warning_distance:
                self.logger.log(
                    LogLevel.WARN,
                    "ADAS",
                    f"** COLLISION WARNING: Track {track.track_id} at {distance:.1f}m! **"
                )
    
    def process_tracks(self, tracks_data):
        """Process raw track data (mock deserialization)."""
        # In real implementation, this would deserialize SOME/IP payload
        self.on_track_update(tracks_data)


def main():
    print("=== ADAS Application Demo (Python) ===")
    print("Subscribing to FusionService events...")
    
    import argparse
    logger = ConsoleLogger()
    logger.log(LogLevel.INFO, "Main", "=== ADAS Application (Python) ===")

    config_path = "examples/automotive_pubsub/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    rt = SomeIpRuntime(config_path, "adas_py_instance", logger)
    rt.logger.log(LogLevel.INFO, "Main", "ADAS Application starting...")
    rt.start()
    
    adas = AdasApplication(rt)
    
    # Subscribe to FusionService events
    # FusionService: service_id=0x7002 (28674), eventgroup_id=1
    rt.subscribe_eventgroup(
        service_id=0x7002,
        instance_id=1,
        eventgroup_id=1,
        ttl=100
    )
    
    rt.logger.log(LogLevel.INFO, "Main", "Subscribed to FusionService events. Waiting...")
    
    # In a full demo, we would register an event handler callback
    # For now, we demonstrate the subscription mechanism
    
    try:
        iteration = 0
        while True:
            iteration += 1
            
            # Simulate receiving periodic events (demo mode)
            # In production, events would be pushed via callbacks from the runtime
            if iteration % 4 == 0:
                # Mock receiving some tracks for demo purposes
                demo_tracks = [
                    FusedTrack(track_id=1, position_x=15.0, position_y=2.0, confidence=0.9),
                    FusedTrack(track_id=2, position_x=8.5, position_y=1.0, confidence=0.85),
                ]
                adas.on_track_update(demo_tracks)
            
            time.sleep(0.5)
            
            # Exit after a few iterations for testing
            if iteration >= 6:
                rt.logger.log(LogLevel.INFO, "Main", "Demo completed (6 iterations)")
                break
            
    except KeyboardInterrupt:
        rt.logger.log(LogLevel.INFO, "Main", "Shutting down ADAS application...")
    finally:
        rt.unsubscribe_eventgroup(0x7002, 1, 1)
        rt.stop()


if __name__ == "__main__":
    main()
