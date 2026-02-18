"""
Shared data types for the Integrated Apps demo.

These can be imported by any service definition or application.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class SortData:
    """Data container for sort operations."""
    values: List[int]


@dataclass
class DeviceInfo:
    """Information about a connected device."""
    id: int
    name: str
    is_active: bool
    firmware_version: str


@dataclass
class SystemStatus:
    """System health and device status."""
    uptime: int
    devices: List[DeviceInfo]
    cpu_load: float
