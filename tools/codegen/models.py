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
class Service:
    name: str
    id: int
    methods: List[Method]

@dataclass
class Struct:
    name: str
    fields: List[Field]
