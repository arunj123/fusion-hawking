from dataclasses import dataclass, field
from typing import List, Optional, Tuple

@dataclass
class Type:
    name: str
    is_list: bool = False
    
    def __str__(self):
        if self.is_list:
            return f"Vec<{self.name}>"
        return self.name

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

@dataclass
class Struct:
    name: str
    fields: List[Field]
