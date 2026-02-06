"""
Automotive Publish-Subscribe Interface Definitions

This file defines the service interfaces for the Radar/Fusion/ADAS demo.
These services demonstrate the publish-subscribe pattern using SOME/IP events.

Note: This is an independent implementation inspired by automotive middleware patterns.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Fusion Hawking Contributors
"""
from dataclasses import dataclass
from typing import List

# Mock Decorators (so this file is valid Python)
def service(id): 
    def wrapper(cls):
        cls.service_id = id
        cls.is_service = True
        return cls
    return wrapper

def method(id): 
    return lambda func: func

def event(id):
    return lambda func: func

def field(id, get_id=None, set_id=None, notifier_id=None):
    return lambda func: func


# =============================================================================
# Data Types
# =============================================================================

@dataclass
class RadarObject:
    """A single radar detection point."""
    id: int               # Unique object ID
    range_m: float        # Distance in meters
    velocity_mps: float   # Relative velocity (m/s), negative = approaching
    azimuth_deg: float    # Angle in degrees, 0 = straight ahead

@dataclass
class FusedTrack:
    """A fused track from sensor fusion."""
    track_id: int         # Unique track ID
    position_x: float     # X position in vehicle coordinates (meters)
    position_y: float     # Y position in vehicle coordinates (meters)
    velocity_x: float     # X velocity (m/s)
    velocity_y: float     # Y velocity (m/s)
    confidence: float     # Track confidence [0.0, 1.0]


# =============================================================================
# Service Definitions
# =============================================================================

@service(id=0x7001)  # Service ID: 28673
class RadarService:
    """
    Radar Sensor Service (Publisher)
    
    Hosted by: C++ ECU
    Pattern: Pure Publisher - no RPC methods
    
    Publishes radar detections at ~10 Hz.
    """
    
    @event(id=0x8001)
    def on_object_detected(self, objects: List[RadarObject]):
        """Event: New radar objects detected (published periodically)."""
        ...
    
    @field(id=1, get_id=0x10, notifier_id=0x12)
    def detection_count(self) -> int:
        """Field: Total number of detections since startup."""
        ...


@service(id=0x7002)  # Service ID: 28674
class FusionService:
    """
    Sensor Fusion Service (Subscriber + Publisher)
    
    Hosted by: Rust ECU
    Pattern: Subscribes to RadarService, publishes fused tracks
    
    Receives radar data, performs fusion, and publishes track updates.
    """
    
    @event(id=0x8001)
    def on_track_updated(self, tracks: List[FusedTrack]):
        """Event: Track list updated after fusion (published periodically)."""
        ...
    
    @method(id=1)
    def get_active_tracks(self) -> List[FusedTrack]:
        """RPC: Get current list of active tracks."""
        ...
    
    @method(id=2)
    def reset_tracks(self) -> bool:
        """RPC: Clear all tracked objects."""
        ...
