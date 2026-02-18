"""
Fusion Hawking IDL — Interface Definition Language

This module provides decorators and utilities for defining SOME/IP services
using standard Python classes. The IDL files ARE Python — importable, runnable,
and introspectable.

Usage (in an IDL file):
    from dataclasses import dataclass
    from typing import List
    from fusion_hawking.idl import service, method, event, field

    @dataclass
    class SensorData:
        temperature: float
        pressure: float

    @service(id=0x1001)
    class SensorService:
        @method(id=1)
        def get_reading(self) -> SensorData: ...

        @method(id=2, fire_and_forget=True)
        def calibrate(self, offset: float): ...

        @event(id=0x8001)
        def on_threshold_exceeded(self, value: float): ...

        @field(id=1, get_id=0x10, set_id=0x11, notifier_id=0x12)
        def sample_rate(self) -> int: ...

SPDX-License-Identifier: MIT
Copyright (c) 2026 Fusion Hawking Contributors
"""

import inspect
import typing
import dataclasses
from typing import List, Optional, Dict, Any, get_type_hints


# =============================================================================
# Type Introspection Utilities
# =============================================================================

def resolve_type_info(annotation) -> dict:
    """
    Resolve a Python type annotation to a portable type descriptor.

    Supports:
      - Primitives: int, float, str, bool, bytes
      - Sized integers: int8, int16, int32, int64, uint8, uint16, uint32, uint64
      - Sized floats: float32, float64
      - List[T] (recursive)
      - @dataclass structs (by name, with fields introspected)
      - Nested combinations: List[List[int]], List[MyStruct], struct-in-struct
      - None / NoneType for fire-and-forget methods

    Returns dict with:
      { 'name': str, 'inner': optional_dict, 'fields': optional_list, 'is_dataclass': bool }
    """
    if annotation is None or annotation is type(None):
        return {'name': 'None', 'inner': None, 'is_dataclass': False}

    # Handle typing.List[T], list[T]
    origin = getattr(annotation, '__origin__', None)
    if origin is list:
        args = getattr(annotation, '__args__', ())
        inner = resolve_type_info(args[0]) if args else {'name': 'Unknown', 'inner': None, 'is_dataclass': False}
        return {'name': 'list', 'inner': inner, 'is_dataclass': False}

    # Handle plain types
    if isinstance(annotation, type):
        if dataclasses.is_dataclass(annotation):
            fields = []
            for f in dataclasses.fields(annotation):
                fields.append({
                    'name': f.name,
                    'type': resolve_type_info(f.type)
                })
            return {'name': annotation.__name__, 'inner': None, 'is_dataclass': True, 'fields': fields}

        mapping = {
            int: 'int', float: 'float', str: 'string', bool: 'bool', bytes: 'bytes'
        }
        if annotation in mapping:
            return {'name': mapping[annotation], 'inner': None, 'is_dataclass': False}
        # Unknown class — treat as struct name
        return {'name': annotation.__name__, 'inner': None, 'is_dataclass': False}

    # Handle string annotations (forward references)
    if isinstance(annotation, str):
        return {'name': annotation, 'inner': None, 'is_dataclass': False}

    return {'name': 'Unknown', 'inner': None, 'is_dataclass': False}


# =============================================================================
# Decorators
# =============================================================================

def service(id: int, major_version: int = 1, minor_version: int = 0):
    """
    Mark a class as a SOME/IP Service.

    The decorator introspects all methods decorated with @method, @event,
    and @field, and attaches metadata to the class for codegen and runtime.

    Args:
        id: SOME/IP Service ID (uint16)
        major_version: Major interface version (default 1)
        minor_version: Minor interface version (default 0)
    """
    def wrapper(cls):
        cls._fusion_service_id = id
        cls._fusion_major = major_version
        cls._fusion_minor = minor_version
        cls._fusion_methods = {}
        cls._fusion_events = {}
        cls._fusion_fields = {}

        # Introspect: loop through all class members
        for name in list(vars(cls)):
            obj = vars(cls)[name]
            if callable(obj) or isinstance(obj, (staticmethod, classmethod)):
                fn = obj
                if isinstance(fn, (staticmethod, classmethod)):
                    fn = fn.__func__

                if hasattr(fn, '_fusion_method_id'):
                    # Resolve type hints for arguments and return type
                    try:
                        hints = get_type_hints(fn)
                    except Exception:
                        hints = {}

                    args = []
                    sig = inspect.signature(fn)
                    for pname, param in sig.parameters.items():
                        if pname == 'self':
                            continue
                        arg_type = hints.get(pname, None)
                        args.append({
                            'name': pname,
                            'type': resolve_type_info(arg_type)
                        })

                    ret_type = hints.get('return', None)

                    cls._fusion_methods[name] = {
                        'id': fn._fusion_method_id,
                        'args': args,
                        'return_type': resolve_type_info(ret_type),
                        'fire_and_forget': getattr(fn, '_fusion_fire_and_forget', False),
                    }

                elif hasattr(fn, '_fusion_event_id'):
                    try:
                        hints = get_type_hints(fn)
                    except Exception:
                        hints = {}

                    args = []
                    sig = inspect.signature(fn)
                    for pname, param in sig.parameters.items():
                        if pname == 'self':
                            continue
                        arg_type = hints.get(pname, None)
                        args.append({
                            'name': pname,
                            'type': resolve_type_info(arg_type)
                        })

                    cls._fusion_events[name] = {
                        'id': fn._fusion_event_id,
                        'args': args,
                    }

                elif hasattr(fn, '_fusion_field_id'):
                    try:
                        hints = get_type_hints(fn)
                    except Exception:
                        hints = {}
                    ret_type = hints.get('return', None)

                    cls._fusion_fields[name] = {
                        'id': fn._fusion_field_id,
                        'type': resolve_type_info(ret_type),
                        'get_id': getattr(fn, '_fusion_get_id', None),
                        'set_id': getattr(fn, '_fusion_set_id', None),
                        'notifier_id': getattr(fn, '_fusion_notifier_id', None),
                    }

        return cls
    return wrapper


def method(id: int, fire_and_forget: bool = False):
    """
    Mark a function as a SOME/IP Method (RPC).

    Args:
        id: Method ID (uint16)
        fire_and_forget: If True, this is a REQUEST_NO_RETURN (0x01).
                         No response is sent back to the caller.
    """
    def wrapper(fn):
        fn._fusion_method_id = id
        fn._fusion_fire_and_forget = fire_and_forget
        return fn
    return wrapper


def event(id: int):
    """
    Mark a function as a SOME/IP Event.

    Events are notifications published by a service provider.
    Consumers subscribe to event groups to receive them.

    Args:
        id: Event ID (uint16, typically >= 0x8000 per AUTOSAR)
    """
    def wrapper(fn):
        fn._fusion_event_id = id
        return fn
    return wrapper


def field(id: int, get_id: Optional[int] = None, set_id: Optional[int] = None,
          notifier_id: Optional[int] = None):
    """
    Mark a function as a SOME/IP Field (Getter/Setter/Notifier).

    Fields are observable properties. They can support:
      - get_id: Method ID for a Get request
      - set_id: Method ID for a Set request
      - notifier_id: Event ID for change notifications

    Any combination is valid (read-only, write-only, read-write, observable, etc.)

    Args:
        id: Logical field ID
        get_id: Method ID for Get (optional)
        set_id: Method ID for Set (optional)
        notifier_id: Event ID for change notification (optional)
    """
    def wrapper(fn):
        fn._fusion_field_id = id
        fn._fusion_get_id = get_id
        fn._fusion_set_id = set_id
        fn._fusion_notifier_id = notifier_id
        return fn
    return wrapper


# =============================================================================
# Scanner — Introspect IDL modules to discover services and types
# =============================================================================

def scan_module(module) -> dict:
    """
    Scan a Python module for @service classes and @dataclass types.

    Args:
        module: An imported Python module, or a module path string.
                If string, it will be imported via importlib.

    Returns:
        dict with:
          'services': list of service class objects (with _fusion_* metadata)
          'types': list of dataclass class objects
    """
    if isinstance(module, str):
        import importlib
        module = importlib.import_module(module)

    services = []
    types = []

    for name, obj in inspect.getmembers(module, inspect.isclass):
        if hasattr(obj, '_fusion_service_id'):
            services.append(obj)
        elif dataclasses.is_dataclass(obj) and not hasattr(obj, '_fusion_service_id'):
            types.append(obj)

    return {'services': services, 'types': types}


def scan_package(package_path: str) -> dict:
    """
    Scan an entire Python package (directory with __init__.py) for services and types.

    Recursively imports all submodules and collects all @service and @dataclass.

    Args:
        package_path: Dotted module path, e.g. 'examples.integrated_apps.idl'

    Returns:
        dict with 'services' and 'types' lists (deduplicated)
    """
    import importlib
    import pkgutil

    pkg = importlib.import_module(package_path)
    all_services = []
    all_types = []
    seen = set()

    # Scan the package itself
    result = scan_module(pkg)
    for s in result['services']:
        if id(s) not in seen:
            all_services.append(s)
            seen.add(id(s))
    for t in result['types']:
        if id(t) not in seen:
            all_types.append(t)
            seen.add(id(t))

    # Scan submodules
    if hasattr(pkg, '__path__'):
        for importer, modname, ispkg in pkgutil.walk_packages(
                pkg.__path__, prefix=package_path + '.'):
            try:
                submod = importlib.import_module(modname)
                result = scan_module(submod)
                for s in result['services']:
                    if id(s) not in seen:
                        all_services.append(s)
                        seen.add(id(s))
                for t in result['types']:
                    if id(t) not in seen:
                        all_types.append(t)
                        seen.add(id(t))
            except Exception as e:
                print(f"Warning: Could not scan {modname}: {e}")

    return {'services': all_services, 'types': all_types}
