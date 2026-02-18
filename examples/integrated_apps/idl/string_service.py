"""
StringService — Python String Service

Provides string manipulation operations.
"""
from fusion_hawking.idl import service, method


@service(id=0x2001)
class StringService:
    @method(id=1)
    def reverse(self, text: str) -> str: ...

    @method(id=2)
    def uppercase(self, text: str) -> str: ...
