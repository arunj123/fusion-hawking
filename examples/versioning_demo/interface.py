"""
Versioning Demo IDL

Demonstrates SOME/IP service versioning with major version changes.
"""
from fusion_hawking.idl import service, method


@service(id=0x2000, major_version=1)
class IVersionedService_v1:
    @method(id=1)
    def method_v1(self, x: int) -> int: ...


@service(id=0x2000, major_version=2)
class IVersionedService_v2:
    @method(id=1)
    def method_v2(self, x: int, y: int) -> int: ...
