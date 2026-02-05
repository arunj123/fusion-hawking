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

# Complex Types
@dataclass
class SortData:
    values: List[int]

@dataclass
class DeviceInfo:
    id: int
    name: str
    is_active: bool
    firmware_version: str

@dataclass
class SystemStatus:
    uptime: int
    devices: List[DeviceInfo]
    cpu_load: float

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

# Service 4: Global Complex Type Service (Hosted by Rust)
@service(id=0x4001)
class ComplexTypeService:
    @method(id=1)
    def check_health(self) -> bool: ...
    
    @method(id=2)
    def set_threshold(self, value: float) -> None: ...
    
    @method(id=3)
    def update_system_status(self, status: SystemStatus) -> bool: ...
    
    @method(id=4)
    def get_devices(self) -> List[DeviceInfo]: ...

    @event(id=0x8001)
    def on_critical_error(self, code: int, message: str): ...

# Service 5: Python Diagnostic Service
@service(id=0x5001)
class DiagnosticService:
    @method(id=1)
    def get_version(self) -> str: ...
    
    @method(id=2)
    def run_self_test(self, level: int) -> bool: ...

# Service 6: C++ Sensor Service
@service(id=0x6001)
class SensorService:
    @field(id=1, get_id=0x10, notifier_id=0x12)
    def temperature(self) -> float: ...
    
    @event(id=0x8001)
    def on_value_changed(self, value: float): ...

