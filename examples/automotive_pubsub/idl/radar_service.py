"""
RadarService — C++ Radar Sensor Service (Publisher)

Pure publisher — no RPC methods, only events and fields.
Publishes radar detections at ~10 Hz.
"""
from typing import List
from fusion_hawking.idl import service, event, field
from .types import RadarObject


@service(id=0x7001)
class RadarService:
    @event(id=0x8001)
    def on_object_detected(self, objects: List[RadarObject]):
        """Event: New radar objects detected (published periodically)."""
        ...

    @field(id=1, get_id=0x10, notifier_id=0x12)
    def detection_count(self) -> int:
        """Field: Total number of detections since startup."""
        ...
