"""
MathService — Rust Math Service

Provides basic arithmetic operations. Demonstrates request/response RPC.
"""
from fusion_hawking.idl import service, method


@service(id=0x1001)
class MathService:
    @method(id=1)
    def add(self, a: int, b: int) -> int: ...

    @method(id=2)
    def sub(self, a: int, b: int) -> int: ...
