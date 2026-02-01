from dataclasses import dataclass
from typing import List

# Service 1: Rust Math Service
@dataclass
class RustMathRequest:
    op: int # 1: Add, 2: Subtract, 3: Multiply
    a: int
    b: int

@dataclass
class RustMathResponse:
    result: int

# Service 2: Python String Service
@dataclass
class PyStringRequest:
    op: int # 1: Reverse, 2: Uppercase
    text: str

@dataclass
class PyStringResponse:
    result: str

# Service 3: C++ Sort Service
@dataclass
class CppSortRequest:
    method: int # 1: Ascending, 2: Descending
    data: List[int]

@dataclass
class CppSortResponse:
    sorted_data: List[int]
