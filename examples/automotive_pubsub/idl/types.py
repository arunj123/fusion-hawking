"""
Shared data types for the Automotive Pub-Sub demo.
"""
from dataclasses import dataclass
from typing import List


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
