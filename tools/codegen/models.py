from dataclasses import dataclass, field
from typing import List, Optional, Tuple

@dataclass
class Type:
    name: str
    inner: Optional['Type'] = None  # For List[T], inner is T
    
    def __str__(self):
        if self.inner:
            return f"Vec<{self.inner}>"
        return self.name

    @property
    def is_list(self) -> bool:
        return self.inner is not None

@dataclass
class Field:
    name: str
    type: Type

@dataclass
class Method:
    name: str
    id: int
    args: List[Field]
    ret_type: Type

@dataclass
class Event:
    name: str
    id: int
    args: List[Field]

@dataclass
class FieldSpec: # Named FieldSpec to avoid conflict with Field
    name: str
    id: int
    type: Type
    get_id: Optional[int] = None
    set_id: Optional[int] = None
    notifier_id: Optional[int] = None

@dataclass
class Service:
    name: str
    id: int
    methods: List[Method] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    fields: List[FieldSpec] = field(default_factory=list)
    major_version: int = 1
    minor_version: int = 0

@dataclass
class Struct:
    name: str
    fields: List[Field]
