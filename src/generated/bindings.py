import struct
from typing import List, Any
import socket
import threading
import time

class SomeIpMessage: pass
def pack_u32(val): return struct.pack('>I', val)
def unpack_u32(data, off): return struct.unpack_from('>I', data, off)[0], off+4

class SortData:
    def __init__(self, values):
        self.values = values
    def serialize(self) -> bytes:
        buffer = bytearray()
        temp_buf = bytearray()
        for item in self.values:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)

# --- Service MathService ---
class MathServiceAddRequest:
    def __init__(self, a, b):
        self.a = a
        self.b = b
    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.a))
        buffer.extend(struct.pack('>i', self.b))
        return bytes(buffer)
class MathServiceAddResponse:
    def __init__(self, result):
        self.result = result
    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.result))
        return bytes(buffer)

class MathServiceSubRequest:
    def __init__(self, a, b):
        self.a = a
        self.b = b
    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.a))
        buffer.extend(struct.pack('>i', self.b))
        return bytes(buffer)
class MathServiceSubResponse:
    def __init__(self, result):
        self.result = result
    def serialize(self) -> bytes:
        buffer = bytearray()
        buffer.extend(struct.pack('>i', self.result))
        return bytes(buffer)

class MathServiceStub:
    SERVICE_ID = 0x1001
    def handle_request(self, data, addr, sock):
        if len(data) < 16: return False
        svc_id, method_id, length, req_id, proto, ver, type_, ret = struct.unpack('>HHIIBBBB', data[:16])
        if svc_id != self.SERVICE_ID: return False
        payload = data[16:]
        
        if method_id == 1:
            # Deserialize MathServiceAddRequest
            off = 0
            a = struct.unpack_from('>i', payload, off)[0]; off+=4
            b = struct.unpack_from('>i', payload, off)[0]; off+=4
            result = self.add(a, b)
            resp = MathServiceAddResponse(result)
            res_payload = resp.serialize()
            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)
            sock.sendto(hdr + res_payload, addr)
            return True
        if method_id == 2:
            # Deserialize MathServiceSubRequest
            off = 0
            a = struct.unpack_from('>i', payload, off)[0]; off+=4
            b = struct.unpack_from('>i', payload, off)[0]; off+=4
            result = self.sub(a, b)
            resp = MathServiceSubResponse(result)
            res_payload = resp.serialize()
            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)
            sock.sendto(hdr + res_payload, addr)
            return True
        return False
class MathServiceClient:
    SERVICE_ID = 0x1001
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
    def add(self, a, b):
        req = MathServiceAddRequest(a, b)
        payload = req.serialize()
        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret
        hdr = struct.pack('>HHIIBBBB', 4097, 1, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)
        self.sock.sendto(hdr + payload, self.addr)

    def sub(self, a, b):
        req = MathServiceSubRequest(a, b)
        payload = req.serialize()
        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret
        hdr = struct.pack('>HHIIBBBB', 4097, 2, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)
        self.sock.sendto(hdr + payload, self.addr)

# --- Service StringService ---
class StringServiceReverseRequest:
    def __init__(self, text):
        self.text = text
    def serialize(self) -> bytes:
        buffer = bytearray()
        b = self.text.encode('utf-8')
        buffer.extend(struct.pack('>I', len(b)))
        buffer.extend(b)
        return bytes(buffer)
class StringServiceReverseResponse:
    def __init__(self, result):
        self.result = result
    def serialize(self) -> bytes:
        buffer = bytearray()
        b = self.result.encode('utf-8')
        buffer.extend(struct.pack('>I', len(b)))
        buffer.extend(b)
        return bytes(buffer)

class StringServiceUppercaseRequest:
    def __init__(self, text):
        self.text = text
    def serialize(self) -> bytes:
        buffer = bytearray()
        b = self.text.encode('utf-8')
        buffer.extend(struct.pack('>I', len(b)))
        buffer.extend(b)
        return bytes(buffer)
class StringServiceUppercaseResponse:
    def __init__(self, result):
        self.result = result
    def serialize(self) -> bytes:
        buffer = bytearray()
        b = self.result.encode('utf-8')
        buffer.extend(struct.pack('>I', len(b)))
        buffer.extend(b)
        return bytes(buffer)

class StringServiceStub:
    SERVICE_ID = 0x2001
    def handle_request(self, data, addr, sock):
        if len(data) < 16: return False
        svc_id, method_id, length, req_id, proto, ver, type_, ret = struct.unpack('>HHIIBBBB', data[:16])
        if svc_id != self.SERVICE_ID: return False
        payload = data[16:]
        
        if method_id == 1:
            # Deserialize StringServiceReverseRequest
            off = 0
            l = struct.unpack_from('>I', payload, off)[0]; off+=4
            text = payload[off:off+l].decode('utf-8'); off+=l
            result = self.reverse(text)
            resp = StringServiceReverseResponse(result)
            res_payload = resp.serialize()
            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)
            sock.sendto(hdr + res_payload, addr)
            return True
        if method_id == 2:
            # Deserialize StringServiceUppercaseRequest
            off = 0
            l = struct.unpack_from('>I', payload, off)[0]; off+=4
            text = payload[off:off+l].decode('utf-8'); off+=l
            result = self.uppercase(text)
            resp = StringServiceUppercaseResponse(result)
            res_payload = resp.serialize()
            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)
            sock.sendto(hdr + res_payload, addr)
            return True
        return False
class StringServiceClient:
    SERVICE_ID = 0x2001
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
    def reverse(self, text):
        req = StringServiceReverseRequest(text)
        payload = req.serialize()
        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret
        hdr = struct.pack('>HHIIBBBB', 8193, 1, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)
        self.sock.sendto(hdr + payload, self.addr)

    def uppercase(self, text):
        req = StringServiceUppercaseRequest(text)
        payload = req.serialize()
        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret
        hdr = struct.pack('>HHIIBBBB', 8193, 2, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)
        self.sock.sendto(hdr + payload, self.addr)

# --- Service SortService ---
class SortServiceSortAscRequest:
    def __init__(self, data):
        self.data = data
    def serialize(self) -> bytes:
        buffer = bytearray()
        temp_buf = bytearray()
        for item in self.data:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)
class SortServiceSortAscResponse:
    def __init__(self, result):
        self.result = result
    def serialize(self) -> bytes:
        buffer = bytearray()
        temp_buf = bytearray()
        for item in self.result:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)

class SortServiceSortDescRequest:
    def __init__(self, data):
        self.data = data
    def serialize(self) -> bytes:
        buffer = bytearray()
        temp_buf = bytearray()
        for item in self.data:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)
class SortServiceSortDescResponse:
    def __init__(self, result):
        self.result = result
    def serialize(self) -> bytes:
        buffer = bytearray()
        temp_buf = bytearray()
        for item in self.result:
            temp_buf.extend(struct.pack('>i', item))
        buffer.extend(struct.pack('>I', len(temp_buf)))
        buffer.extend(temp_buf)
        return bytes(buffer)

class SortServiceStub:
    SERVICE_ID = 0x3001
    def handle_request(self, data, addr, sock):
        if len(data) < 16: return False
        svc_id, method_id, length, req_id, proto, ver, type_, ret = struct.unpack('>HHIIBBBB', data[:16])
        if svc_id != self.SERVICE_ID: return False
        payload = data[16:]
        
        if method_id == 1:
            # Deserialize SortServiceSortAscRequest
            off = 0
            data = struct.unpack_from('>i', payload, off)[0]; off+=4
            result = self.sort_asc(data)
            resp = SortServiceSortAscResponse(result)
            res_payload = resp.serialize()
            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)
            sock.sendto(hdr + res_payload, addr)
            return True
        if method_id == 2:
            # Deserialize SortServiceSortDescRequest
            off = 0
            data = struct.unpack_from('>i', payload, off)[0]; off+=4
            result = self.sort_desc(data)
            resp = SortServiceSortDescResponse(result)
            res_payload = resp.serialize()
            hdr = struct.pack('>HHIIBBBB', svc_id, method_id, len(res_payload)+8, req_id, proto, ver, 0x80, ret)
            sock.sendto(hdr + res_payload, addr)
            return True
        return False
class SortServiceClient:
    SERVICE_ID = 0x3001
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
    def sort_asc(self, data):
        req = SortServiceSortAscRequest(data)
        payload = req.serialize()
        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret
        hdr = struct.pack('>HHIIBBBB', 12289, 1, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)
        self.sock.sendto(hdr + payload, self.addr)

    def sort_desc(self, data):
        req = SortServiceSortDescRequest(data)
        payload = req.serialize()
        # Header: SvcID, MethodID, Len, ReqID, Proto, Ver, Type, Ret
        hdr = struct.pack('>HHIIBBBB', 12289, 2, len(payload)+8, 0x11110001, 0x01, 0x01, 0x00, 0x00)
        self.sock.sendto(hdr + payload, self.addr)
