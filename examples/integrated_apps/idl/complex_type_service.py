"""
ComplexTypeService — Complex Type Service (Hosted by Rust)

Demonstrates complex types: nested structs, List[Struct], fire-and-forget.
"""
from typing import List
from fusion_hawking.idl import service, method, event
from .types import DeviceInfo, SystemStatus


@service(id=0x4001)
class ComplexTypeService:
    @method(id=1)
    def check_health(self) -> bool: ...

    @method(id=2, fire_and_forget=True)
    def set_threshold(self, value: float): ...

    @method(id=3)
    def update_system_status(self, status: SystemStatus) -> bool: ...

    @method(id=4)
    def get_devices(self) -> List[DeviceInfo]: ...

    @event(id=0x8001)
    def on_critical_error(self, code: int, message: str): ...
