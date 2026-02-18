"""
SensorService — C++ Sensor Service

Read-only field with change notification event.
"""
from fusion_hawking.idl import service, field, event


@service(id=0x6001)
class SensorService:
    @field(id=1, get_id=0x10, notifier_id=0x12)
    def temperature(self) -> float: ...

    @event(id=0x8001)
    def on_value_changed(self, value: float): ...
