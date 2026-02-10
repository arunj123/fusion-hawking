"""
Shared ID definitions for the someipy demo.
In a real scenario, these would be generated from an IDL file.
"""

# Service ID (Must match config and other languages)
SOMEIPY_SERVICE_ID = 0x1234 
SOMEIPY_INSTANCE_ID = 0x0001
SOMEIPY_MAJOR_VERSION = 1
SOMEIPY_MINOR_VERSION = 0

# Method IDs
SOMEIPY_METHOD_ECHO = 0x0001

# Event IDs
# (None used in the current simple echo demo, but defined for completeness)
SOMEIPY_EVENT_STATUS = 0x8001

# Event Groups
SOMEIPY_EVENTGROUP_STATUS = 0x0001
