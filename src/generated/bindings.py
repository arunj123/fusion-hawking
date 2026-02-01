import struct
from typing import List

class SomeIpMessage:
    pass

def pack_u32(val): return struct.pack('>I', val)
def unpack_u32(data, off): return struct.unpack_from('>I', data, off)[0], off+4

class RustMathRequest:
    def __init__(self, op: int, a: int, b: int):
        self.op = op
        self.a = a
        self.b = b

    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.op))
        buffer.extend(struct.pack('>i', self.a))
        buffer.extend(struct.pack('>i', self.b))
        return bytes(buffer)

class RustMathResponse:
    def __init__(self, result: int):
        self.result = result

    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.result))
        return bytes(buffer)

class PyStringRequest:
    def __init__(self, op: int, text: str):
        self.op = op
        self.text = text

    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.op))
        b = self.text.encode('utf-8')
        buffer.extend(struct.pack('>I', len(b)))
        buffer.extend(b)
        return bytes(buffer)

class PyStringResponse:
    def __init__(self, result: str):
        self.result = result

    def serialize(self) -> bytes:
        buffer = bytearray()
        b = self.result.encode('utf-8')
        buffer.extend(struct.pack('>I', len(b)))
        buffer.extend(b)
        return bytes(buffer)

class CppSortRequest:
    def __init__(self, method: int, data: List[int]):
        self.method = method
        self.data = data

    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.method))
        # data list serialization
        temp_buf = bytearray()
        for item in self.data:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)

class CppSortResponse:
    def __init__(self, sorted_data: List[int]):
        self.sorted_data = sorted_data

    def serialize(self) -> bytes:
        buffer = bytearray()
        # sorted_data list serialization
        temp_buf = bytearray()
        for item in self.sorted_data:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)
