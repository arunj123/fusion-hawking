"""
DiagnosticService — Python Diagnostic Service

Simple diagnostic RPC service.
"""
from fusion_hawking.idl import service, method


@service(id=0x5001)
class DiagnosticService:
    @method(id=1)
    def get_version(self) -> str: ...

    @method(id=2)
    def run_self_test(self, level: int) -> bool: ...
