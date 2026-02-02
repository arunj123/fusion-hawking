from dataclasses import dataclass
from typing import List

# Mock Decorators (so this file is valid Python)
def service(id): 
    return lambda cls: cls
def method(id): 
    return lambda func: func
def event(id):
    return lambda func: func
def field(id, get_id=None, set_id=None, notifier_id=None):
    return lambda func: func

# Complex Types (if needed) are still dataclasses
@dataclass
class SortData:
    values: List[int]

# Service 1: Rust Math Service
@service(id=0x1001)
class MathService:
    @method(id=1)
    def add(self, a: int, b: int) -> int: ...
    
    @method(id=2)
    def sub(self, a: int, b: int) -> int: ...

# Service 2: Python String Service
@service(id=0x2001)
class StringService:
    @method(id=1)
    def reverse(self, text: str) -> str: ...
    
    @method(id=2)
    def uppercase(self, text: str) -> str: ...

# Service 3: C++ Sort Service
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

