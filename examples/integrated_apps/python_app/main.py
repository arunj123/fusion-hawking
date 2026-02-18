"""
Integrated Apps: Python Application

Demonstrates zero-codegen Python — imports types directly from the IDL package.
No build step required for Python; just import and use.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Fusion Hawking Contributors
"""
import sys
import os
import time
import random

# Path setup — only the library itself, no generated code needed
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'python'))
# Also add project root so IDL packages are importable
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fusion_hawking import SomeIpRuntime, LogLevel, ConsoleLogger, RequestHandler

# Zero-codegen: import types directly from the IDL package
from examples.integrated_apps.idl.types import SystemStatus, DeviceInfo, SortData
from examples.integrated_apps.idl.math_service import MathService
from examples.integrated_apps.idl.string_service import StringService
from examples.integrated_apps.idl.sort_service import SortService
from examples.integrated_apps.idl.diagnostic_service import DiagnosticService
from examples.integrated_apps.idl.complex_type_service import ComplexTypeService

# Use the generated Python stubs if available (backward compat path)
# Fall back to a simple inline implementation
try:
    _gen_python = os.path.join(ROOT, 'build', 'generated', 'integrated_apps', 'python')
    if os.path.exists(_gen_python):
        sys.path.insert(0, _gen_python)
    from runtime import (
        StringServiceStub, StringServiceClient,
        MathServiceStub, MathServiceClient,
        DiagnosticServiceStub,
        ComplexTypeServiceClient,
        SortServiceClient,
    )
    from bindings import SystemStatus as _GenSystemStatus, DeviceInfo as _GenDeviceInfo
    _USE_GENERATED = True
except ImportError:
    _USE_GENERATED = False


class StringImpl(RequestHandler):
    """String service implementation — uses IDL metadata for service/method IDs."""
    SERVICE_ID = StringService._fusion_service_id
    MAJOR_VERSION = StringService._fusion_major
    MINOR_VERSION = StringService._fusion_minor

    def __init__(self, logger):
        self.logger = logger

    def get_service_id(self): return self.SERVICE_ID
    def get_major_version(self): return self.MAJOR_VERSION
    def get_minor_version(self): return self.MINOR_VERSION

    def handle(self, header, payload):
        mid = header['method_id']
        # Method IDs from IDL metadata
        reverse_id = StringService._fusion_methods['reverse']['id']
        upper_id = StringService._fusion_methods['uppercase']['id']

        if mid == reverse_id:
            # Deserialize: 4-byte length-prefixed string
            import struct
            slen = struct.unpack_from('>I', payload, 0)[0]
            text = payload[4:4+slen].decode('utf-8')
            result = text[::-1]
            self.logger.log(LogLevel.INFO, "StringService", f"Reversing '{text}' -> '{result}'")
            result_b = result.encode('utf-8')
            return struct.pack('>I', len(result_b)) + result_b
        elif mid == upper_id:
            import struct
            slen = struct.unpack_from('>I', payload, 0)[0]
            text = payload[4:4+slen].decode('utf-8')
            result = text.upper()
            result_b = result.encode('utf-8')
            return struct.pack('>I', len(result_b)) + result_b
        return None

    def reverse(self, text): return text[::-1]
    def uppercase(self, text): return text.upper()


class DiagImpl(RequestHandler):
    """Diagnostic service implementation."""
    SERVICE_ID = DiagnosticService._fusion_service_id
    MAJOR_VERSION = DiagnosticService._fusion_major
    MINOR_VERSION = DiagnosticService._fusion_minor

    def get_service_id(self): return self.SERVICE_ID
    def get_major_version(self): return self.MAJOR_VERSION
    def get_minor_version(self): return self.MINOR_VERSION

    def handle(self, header, payload):
        import struct
        mid = header['method_id']
        get_version_id = DiagnosticService._fusion_methods['get_version']['id']
        if mid == get_version_id:
            result = "1.2.3-py"
            result_b = result.encode('utf-8')
            return struct.pack('>I', len(result_b)) + result_b
        return None

    def get_version(self): return "1.2.3-py"
    def run_self_test(self, level): return True


class MathImpl(RequestHandler):
    """Math service implementation."""
    SERVICE_ID = MathService._fusion_service_id
    MAJOR_VERSION = MathService._fusion_major
    MINOR_VERSION = MathService._fusion_minor

    def __init__(self, logger, instance_id):
        self.logger = logger
        self.instance_id = instance_id

    def get_service_id(self): return self.SERVICE_ID
    def get_major_version(self): return self.MAJOR_VERSION
    def get_minor_version(self): return self.MINOR_VERSION

    def handle(self, header, payload):
        import struct
        mid = header['method_id']
        add_id = MathService._fusion_methods['add']['id']
        sub_id = MathService._fusion_methods['sub']['id']
        if mid == add_id:
            a, b = struct.unpack_from('>ii', payload)
            result = self.add(a, b)
            return struct.pack('>i', result)
        elif mid == sub_id:
            a, b = struct.unpack_from('>ii', payload)
            result = self.sub(a, b)
            return struct.pack('>i', result)
        return None

    def add(self, a, b):
        self.logger.log(LogLevel.INFO, "MathService", f"[{self.instance_id}] Add({a}, {b})")
        return a + b

    def sub(self, a, b):
        return a - b


def _make_client(rt, alias, service_cls):
    """Create a simple client wrapper using IDL metadata."""
    if _USE_GENERATED:
        # Use generated client if available
        client_name = service_cls.__name__ + "Client"
        import importlib
        try:
            mod = sys.modules.get('runtime')
            if mod and hasattr(mod, client_name):
                return getattr(mod, client_name)(rt, alias)
        except Exception:
            pass
    return rt.get_client(alias, None)


def main():
    ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    logger = ConsoleLogger()
    logger.log(LogLevel.INFO, "Main", "=== Integrated Python Application (Zero-Codegen) ===")

    config_path = "examples/integrated_apps/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    rt = SomeIpRuntime(config_path, "python_app_instance", logger)
    rt.logger.log(LogLevel.INFO, "Main", f"--- Python Runtime Demo (Config: {config_path}) ---")
    rt.start()

    # Offer services using IDL-derived metadata
    rt.offer_service("string-service", StringImpl(rt.logger))
    rt.offer_service("diagnostic-service", DiagImpl())
    rt.offer_service("math-service", MathImpl(rt.logger, 3))

    time.sleep(2)

    try:
        while True:
            # Client calls — use generated clients if available, else raw runtime
            if _USE_GENERATED:
                from runtime import MathServiceClient, SortServiceClient, ComplexTypeServiceClient
                from bindings import SystemStatus as GenStatus, DeviceInfo as GenDevice

                math = rt.get_client("math-client", MathServiceClient)
                if math:
                    rt.logger.log(LogLevel.INFO, "Client", "Sending Add...")
                    math.add(random.randint(0, 50), random.randint(0, 50))

                sort_svc = rt.get_client("sort-client", SortServiceClient)
                if sort_svc:
                    rt.logger.log(LogLevel.INFO, "Client", "Sending Sort...")
                    sort_svc.sort_asc([5, 3, 1, 4, 2])

                complex_svc = rt.get_client("complex-client", ComplexTypeServiceClient)
                if complex_svc:
                    complex_svc.check_health()
                    status = GenStatus(
                        uptime=int(time.time()),
                        devices=[GenDevice(id=101, name="PySensor", is_active=True, firmware_version="2.0")],
                        cpu_load=0.5
                    )
                    complex_svc.update_system_status(status)
            else:
                rt.logger.log(LogLevel.INFO, "Client", "Generated stubs not available, skipping client calls")

            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop()


if __name__ == "__main__":
    main()
