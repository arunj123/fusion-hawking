import sys
import os
import socket
import struct
import threading
import time

# Add generated bindings to path
# Assuming we run from root
gen_path = os.path.join(os.getcwd(), 'src', 'generated')
sys.path.append(gen_path)

try:
    import bindings
    from bindings import PyStringRequest, PyStringResponse, RustMathRequest, CppSortRequest
except ImportError:
    print("Failed to import bindings. Run codegenerator.py first.")
    sys.exit(1)


# Global for discovered services
MATH_ADDR = None
STRING_PORT = 30502
SORT_ADDR = ('127.0.0.1', 30503)

def sd_listener():
    global MATH_ADDR
    MCAST_GRP = '224.0.0.1'
    MCAST_PORT = 30490
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Bind to 30490 on all interfaces
    sock.bind(('', MCAST_PORT))
    
    # Join Multicast
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    print(f"SD Listener started on {MCAST_GRP}:{MCAST_PORT}")
    
    while True:
        try:
            data, addr = sock.recvfrom(10240)
            if len(data) < 16 + 12: # Header + Min SD Packet
                continue
                
            # Skip SOME/IP Header (16 bytes)
            sd_payload = data[16:]
            
            # SD Header: Flags(1), Res(3), EntriesLen(4)
            entries_len = struct.unpack('>I', sd_payload[4:8])[0]
            entries_offset = 8
            
            # Parse Entries
            curr = entries_offset
            entries_end = curr + entries_len
            
            entries = []
            while curr < entries_end:
                # Type(1), Idx1(1), Idx2(1), NumOpt(1) -> (NumOpt1 << 4 | NumOpt2)
                # SvcID(2), InstID(2), Maj(1), TTL(3), Min(4)
                
                type_ = sd_payload[curr]
                idx1 = sd_payload[curr+1]
                idx2 = sd_payload[curr+2]
                num_opts_byte = sd_payload[curr+3]
                num_opt1 = (num_opts_byte & 0xF0) >> 4
                num_opt2 = (num_opts_byte & 0x0F)
                
                svc_id = struct.unpack('>H', sd_payload[curr+4:curr+6])[0]
                inst_id = struct.unpack('>H', sd_payload[curr+6:curr+8])[0]
                ttl_bytes = b'\x00' + sd_payload[curr+9:curr+12]
                ttl = struct.unpack('>I', ttl_bytes)[0]
                
                entries.append({
                    'type': type_,
                    'svc_id': svc_id,
                    'inst_id': inst_id,
                    'ttl': ttl,
                    'idx1': idx1,
                    'num1': num_opt1
                })
                curr += 16
            
            # Parse Options
            options_len_offset = entries_end
            if len(sd_payload) < options_len_offset + 4:
                continue
                
            options_len = struct.unpack('>I', sd_payload[options_len_offset:options_len_offset+4])[0]
            options_start = options_len_offset + 4
            
            # We need to index options to look them up by index
            options_list = []
            curr_opt = options_start
            options_end = curr_opt + options_len
            
            while curr_opt < options_end:
                # Len(2), Type(1)
                opt_len = struct.unpack('>H', sd_payload[curr_opt:curr_opt+2])[0]
                opt_type = sd_payload[curr_opt+2]
                
                # Payload including Type and Res is opt_len + 3? No.
                # Spec: Length field indicates bytes AFTER Type.
                # Total option size = 2 (Len) + 1 (Type) + LengthValue.
                # WAIT. My serialization logic:
                # Length = Total - 3.
                # So Total = Length + 3.
                # Read total bytes
                chunk = sd_payload[curr_opt : curr_opt + 3 + opt_len]
                options_list.append({'type': opt_type, 'data': chunk})
                
                curr_opt += 3 + opt_len

            # Check for Math Service Offer (0x1001)
            for e in entries:
                if e['type'] == 0x01 and e['svc_id'] == 0x1001: # Offer Service
                    if e['ttl'] > 0:
                        # Found offer! Get Endpoint.
                        # Index 1
                        idx = e['idx1']
                        count = e['num1']
                        if idx < len(options_list):
                            opt = options_list[idx] # Assuming contiguous options for MVP
                            if opt['type'] == 0x04: # IPv4
                                # Parse IPv4 Option
                                # [Len:2][Type:1][Res:1][IPv4:4][Res:1][L4:1][Port:2]
                                # Data chunk: [Len:2][Type:1] ...
                                # Port is at offset 10
                                port = struct.unpack('>H', opt['data'][10:12])[0]
                                ip_bytes = opt['data'][4:8]
                                ip_str = socket.inet_ntoa(ip_bytes)
                                
                                # Update Global
                                MATH_ADDR = (ip_str, port)
        except Exception as e:
            # print(f"SD Listener Error: {e}")
            pass

def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', STRING_PORT))
    print(f"Python String Service listening on {STRING_PORT}...")
    
    while True:
        data, addr = sock.recvfrom(2048)
        if len(data) < 16:
            continue
            
        # Parse SOME/IP Header (Naive)
        svc_id = struct.unpack('>H', data[0:2])[0]
        method_id = struct.unpack('>H', data[2:4])[0]
        
        # String Service: 0x2001/0x0001
        if svc_id == 0x2001 and method_id == 0x0001:
            try:
                # Payload starts at 16
                # Naive unpack for PyStringRequest
                # Op(4), Len(4), Bytes...
                op = struct.unpack('>i', data[16:20])[0]
                str_len = struct.unpack('>I', data[20:24])[0]
                text = data[24:24+str_len].decode('utf-8')
                
                print(f"Python Service received: op={op}, text='{text}'")
                
                # Logic
                res_text = text[::-1] if op == 1 else text.upper()
                
                # Response
                resp = PyStringResponse(result=res_text)
                payload = resp.serialize()
                
                # Header
                req_id_bytes = data[8:12]
                hdr = struct.pack('>HH I 4s BBBB', svc_id, method_id, len(payload)+8, req_id_bytes, 0x01, 0x01, 0x80, 0x00)
                
                sock.sendto(hdr + payload, addr)
                
            except Exception as e:
                print(f"Error processing request: {e}")

def run_client():
    print("Python Client: Waiting for Math Service Discovery...")
    while MATH_ADDR is None:
        time.sleep(0.5)
        
    print(f"Python Client: Discovered Math Service at {MATH_ADDR}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # 1. Call Rust Math (0x1001, 0x0001) - Add 10 + 5
    req = RustMathRequest(op=1, a=10, b=5)
    payload = req.serialize()
    
    hdr = struct.pack('>HHIIBBBB', 0x1001, 0x0001, len(payload)+8, 0x22220001, 0x01, 0x01, 0x00, 0x00)
    sock.sendto(hdr + payload, MATH_ADDR)
    print("Python Client: Sent request to Rust Math Service")
    
    # 2. Call C++ Sort (0x3001, 0x0001)
    req = CppSortRequest(method=2, data=[10, 20, 5, 100])
    payload = req.serialize()
    
    hdr = struct.pack('>HHIIBBBB', 0x3001, 0x0001, len(payload)+8, 0x22220002, 0x01, 0x01, 0x00, 0x00)
    sock.sendto(hdr + payload, SORT_ADDR)
    print("Python Client: Sent request to C++ Sort Service")

if __name__ == "__main__":
    t_server = threading.Thread(target=run_server)
    t_server.daemon = True
    t_server.start()
    
    t_sd = threading.Thread(target=sd_listener)
    t_sd.daemon = True
    t_sd.start()
    
    run_client()
    
    while True:
        time.sleep(1)

