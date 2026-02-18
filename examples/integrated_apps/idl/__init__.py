"""
Integrated Apps IDL Package

This package defines all service interfaces and shared types for the
Integrated Apps demo. Each service is defined in its own module.

Usage:
    from examples.integrated_apps.idl import MathService, StringService
    from examples.integrated_apps.idl.types import SortData, DeviceInfo
"""

# Types
from .types import SortData, DeviceInfo, SystemStatus

# Services — import for convenient access
from .math_service import MathService
from .string_service import StringService
from .sort_service import SortService
from .complex_type_service import ComplexTypeService
from .diagnostic_service import DiagnosticService
from .sensor_service import SensorService
