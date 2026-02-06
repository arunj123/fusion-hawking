import dataclasses
from typing import List

def service(id):
    def inner(cls): return cls
    return inner

def method(id):
    def inner(func): return func
    return inner

@dataclasses.dataclass
class Point:
    x: int
    y: int

@dataclasses.dataclass
class PointList:
    points: List[Point]

@service(id=0x1000)
class MapService:
    @method(id=1)
    def get_path(self, start: Point, end: Point) -> List[Point]:
        pass

    @method(id=2)
    def add_points(self, points: List[Point]):
        pass
