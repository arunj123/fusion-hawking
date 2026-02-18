"""
Introspection-based IDL scanner.

Replaces the old AST-based parser. Imports IDL modules and uses Python
introspection to discover @service classes and @dataclass types.

The scanner produces the same model objects (Service, Struct, etc.) as
the old parser, so generators can consume them without changes.
"""

import sys
import os
import importlib
import inspect
import dataclasses
from typing import get_type_hints, List, Optional

from .models import Service, Struct, Field, Type, Method, Event, FieldSpec


def _resolve_type(annotation) -> Type:
    """Convert a Python type annotation to a codegen Type object."""
    if annotation is None or annotation is type(None):
        return Type("None")

    origin = getattr(annotation, '__origin__', None)
    if origin is list:
        args = getattr(annotation, '__args__', ())
        inner = _resolve_type(args[0]) if args else Type("Unknown")
        return Type("list", inner=inner)

    if isinstance(annotation, type):
        if dataclasses.is_dataclass(annotation):
            return Type(annotation.__name__)

        mapping = {
            int: 'int', float: 'float32', str: 'string', bool: 'bool', bytes: 'bytes'
        }
        return Type(mapping.get(annotation, annotation.__name__))

    if isinstance(annotation, str):
        return Type(annotation)

    return Type("Unknown")


def _scan_dataclass(cls) -> Struct:
    """Convert a @dataclass into a codegen Struct."""
    fields = []
    for f in dataclasses.fields(cls):
        # Resolve the type annotation properly
        hints = get_type_hints(cls)
        annotation = hints.get(f.name, f.type)
        fields.append(Field(f.name, _resolve_type(annotation)))
    return Struct(cls.__name__, fields)


def _scan_service(cls) -> Service:
    """Convert a @service class (with _fusion_* metadata) into a codegen Service."""
    methods = []
    events = []
    fields = []

    for mname, minfo in cls._fusion_methods.items():
        args = []
        for arg in minfo['args']:
            t = _type_from_info(arg['type'])
            args.append(Field(arg['name'], t))

        ret = _type_from_info(minfo['return_type'])
        m = Method(mname, minfo['id'], args, ret)
        m.fire_and_forget = minfo.get('fire_and_forget', False)
        methods.append(m)

    for ename, einfo in cls._fusion_events.items():
        args = []
        for arg in einfo['args']:
            t = _type_from_info(arg['type'])
            args.append(Field(arg['name'], t))
        events.append(Event(ename, einfo['id'], args))

    for fname, finfo in cls._fusion_fields.items():
        t = _type_from_info(finfo['type'])
        fields.append(FieldSpec(
            fname, finfo['id'], t,
            get_id=finfo.get('get_id'),
            set_id=finfo.get('set_id'),
            notifier_id=finfo.get('notifier_id'),
        ))

    return Service(
        cls.__name__,
        cls._fusion_service_id,
        methods, events, fields,
        cls._fusion_major,
        cls._fusion_minor,
    )


def _type_from_info(info: dict) -> Type:
    """Convert a type info dict (from resolve_type_info) back to a codegen Type."""
    name = info['name']
    inner = None
    if info.get('inner'):
        inner = _type_from_info(info['inner'])
    return Type(name, inner=inner)


def scan(module_path: str, project_root: str = None) -> tuple[list[Struct], list[Service]]:
    """
    Scan an IDL module/package via Python introspection.

    Args:
        module_path: Dotted module path, e.g. 'examples.integrated_apps.idl'
        project_root: Project root directory (added to sys.path for import)

    Returns:
        (structs, services) — same format as old PythonASTParser.parse()
    """
    if project_root and project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Also ensure src/python is on path for fusion_hawking imports
    python_src = os.path.join(project_root or os.getcwd(), 'src', 'python')
    if python_src not in sys.path:
        sys.path.insert(0, python_src)

    # Use the fusion_hawking.idl scanner to discover classes
    from fusion_hawking.idl import scan_package, scan_module

    # Try as package first, then as module
    try:
        result = scan_package(module_path)
    except Exception:
        result = scan_module(module_path)

    structs = [_scan_dataclass(t) for t in result['types']]
    services = [_scan_service(s) for s in result['services']]

    # Also discover nested struct types referenced by services
    # (types used as method args/returns that might not be top-level)
    known_names = {s.name for s in structs}
    for svc_cls in result['services']:
        _discover_nested_types(svc_cls, result['types'], structs, known_names)

    return structs, services


def _discover_nested_types(svc_cls, known_types, structs, known_names):
    """Discover @dataclass types used in method signatures but not top-level."""
    # Look through all type infos in methods/events/fields
    all_type_infos = []
    for minfo in svc_cls._fusion_methods.values():
        for arg in minfo['args']:
            all_type_infos.append(arg['type'])
        all_type_infos.append(minfo['return_type'])
    for einfo in svc_cls._fusion_events.values():
        for arg in einfo['args']:
            all_type_infos.append(arg['type'])
    for finfo in svc_cls._fusion_fields.values():
        all_type_infos.append(finfo['type'])

    for tinfo in all_type_infos:
        _check_type_info(tinfo, structs, known_names)


def _check_type_info(tinfo, structs, known_names):
    """Recursively check if a type info references a dataclass that needs to be added."""
    if tinfo.get('is_dataclass') and tinfo['name'] not in known_names:
        # Reconstruct struct from the type info's fields
        fields = []
        for f in tinfo.get('fields', []):
            fields.append(Field(f['name'], _type_from_info(f['type'])))
        structs.append(Struct(tinfo['name'], fields))
        known_names.add(tinfo['name'])

    if tinfo.get('inner'):
        _check_type_info(tinfo['inner'], structs, known_names)
