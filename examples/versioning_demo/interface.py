from typing import List

# Mock Decorators
def service(id, major_version=1, minor_version=0): 
    def wrapper(cls):
        cls.service_id = id
        cls.is_service = True
        return cls
    return wrapper
def method(id): 
    return lambda func: func

@service(id=0x2000, major_version=1)
class IVersionedService_v1:
    @method(id=1)
    def method_v1(self, x: int) -> int: ...

@service(id=0x2000, major_version=2)
class IVersionedService_v2:
    @method(id=1)
    def method_v2(self, x: int, y: int) -> int: ...
