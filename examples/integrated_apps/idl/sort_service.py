"""
SortService — C++ Sort Service

Demonstrates methods, events, and fields in a single service.
"""
from typing import List
from fusion_hawking.idl import service, method, event, field


@service(id=0x3001)
class SortService:
    @method(id=1)
    def sort_asc(self, data: List[int]) -> List[int]: ...

    @method(id=2)
    def sort_desc(self, data: List[int]) -> List[int]: ...

    @event(id=0x8001)
    def on_sort_completed(self, count: int): ...

    @field(id=10, get_id=0x10, set_id=0x11, notifier_id=0x12)
    def status(self) -> str: ...
