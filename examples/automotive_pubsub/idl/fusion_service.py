"""
FusionService — Rust Sensor Fusion Service (Subscriber + Publisher)

Subscribes to RadarService, performs fusion, and publishes track updates.
"""
from typing import List
from fusion_hawking.idl import service, method, event
from .types import FusedTrack


@service(id=0x7002)
class FusionService:
    @event(id=0x8001)
    def on_track_updated(self, tracks: List[FusedTrack]):
        """Event: Track list updated after fusion."""
        ...

    @method(id=1)
    def get_active_tracks(self) -> List[FusedTrack]:
        """RPC: Get current list of active tracks."""
        ...

    @method(id=2)
    def reset_tracks(self) -> bool:
        """RPC: Clear all tracked objects."""
        ...
