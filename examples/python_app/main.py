import sys
import os
import socket
import struct
import threading
import time

# Add generated bindings to path
gen_path = os.path.join(os.getcwd(), 'src', 'generated')
sys.path.append(gen_path)

try:
    import bindings
    from bindings import StringServiceStub, MathServiceClient, SortServiceClient
except ImportError:
    print("Failed to import bindings. Run codegenerator.py first.")
    sys.exit(1)

# Global for discovered services
MATH_ADDR = None
STRING_PORT = 30502
SORT_ADDR = ('127.0.0.1', 30503)

# Graceful shutdown event
stop_event = threading.Event()

# --- Service Implementation ---
class StringServiceImpl(StringServiceStub):
    def reverse(self, text):
        print(f"StringService: reverse('{text}')")
        return text[::-1]
    
    def uppercase(self, text):
        print(f"StringService: uppercase('{text}')")
        return text.upper()

def sd_listener():
    global MATH_ADDR
    MCAST_GRP = '224.0.0.1'
    MCAST_PORT = 30490
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', MCAST_PORT))
    
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(1.0) 
    
    print(f"SD Listener started on {MCAST_GRP}:{MCAST_PORT}")
    
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(10240)
            if len(data) < 16 + 12: 
                continue
            
            # Simplified SD Parsing to find Math Service (0x1001)
            # Skip Header (16)
            sd_payload = data[16:]
            entries_len = struct.unpack('>I', sd_payload[4:8])[0]
            entries_end = 8 + entries_len
            
            curr = 8
            while curr < entries_end:
                 type_ = sd_payload[curr]
                 idx1 = sd_payload[curr+1]
                 svc_id = struct.unpack('>H', sd_payload[curr+4:curr+6])[0]
                 ttl = struct.unpack('>I', b'\x00' + sd_payload[curr+9:curr+12])[0]
                 
                 if type_ == 0x01 and svc_id == 0x1001 and ttl > 0:
                     # Find Option for IP/Port
                     # Quick hack: assume option is at idx1 and options start after entries
                     options_len_offset = entries_end
                     options_start = options_len_offset + 4
                     
                     # Calculate option offset (Assuming flat list logic as before or simpler)
                     # For MVP Demo, we iterate options
                     curr_opt = options_start
                     # Skip to target option? 
                     # Let's iterate options until we find one with IPv4 (0x04)
                     # (This is a simplification, ideally check indices)
                     if len(sd_payload) > options_start:
                         options_len = struct.unpack('>I', sd_payload[options_len_offset:options_len_offset+4])[0]
                         o_end = options_start + options_len
                         c_o = options_start
                         while c_o < o_end:
                             opt_len = struct.unpack('>H', sd_payload[c_o:c_o+2])[0]
                             opt_type = sd_payload[c_o+2]
                             if opt_type == 0x04:
                                 port = struct.unpack('>H', sd_payload[c_o+10:c_o+12])[0]
                                 ip_bytes = sd_payload[c_o+4:c_o+8]
                                 ip_str = socket.inet_ntoa(ip_bytes)
                                 MATH_ADDR = (ip_str, port)
                                 break
                             c_o += 3 + opt_len
                 curr += 16
                 
        except socket.timeout:
            continue
        except Exception:
            pass
    print("SD Listener stopped.")

def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', STRING_PORT))
    sock.settimeout(1.0)
    print(f"Python String Service listening on {STRING_PORT}...")
    
    service_impl = StringServiceImpl()
    
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(2048)
            # Use Binder Stub
            # handle_request(data, addr, sock)
            if service_impl.handle_request(data, addr, sock):
                # print("Request handled via Binder")
                pass
            else:
                # print("Invalid request for Binder")
                pass
                
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Server Error: {e}")
    print("Python Server stopped.")

def run_client():
    print("Python Client: Waiting for Math Service Discovery...")
    while MATH_ADDR is None and not stop_event.is_set():
        time.sleep(0.5)
        
    if stop_event.is_set(): return

    print(f"Python Client: Discovered Math Service at {MATH_ADDR}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Init Clients
    math_client = MathServiceClient(sock, MATH_ADDR)
    sort_client = SortServiceClient(sock, SORT_ADDR)
    
    counter = 0
    while not stop_event.is_set():
        counter += 1
        print(f"\n--- Cycle {counter} ---")
        
        # 1. Math Call
        print(f"Python Client: Calling Math.add({counter}, 5)...")
        math_client.add(counter, 5)
        
        # 2. Sort Call
        print(f"Python Client: Calling Sort.sort_desc(...)")
        sort_client.sort_desc([counter, counter+10, 5, 100])
        
        stop_event.wait(2.0)
    print("Python Client stopped.")

if __name__ == "__main__":
    t_server = threading.Thread(target=run_server)
    t_sd = threading.Thread(target=sd_listener)
    
    t_server.start()
    t_sd.start()
    
    try:
        run_client()
    except KeyboardInterrupt:
        print("\nPython: Ctrl+C received. Stopping threads...")
        stop_event.set()
        
    t_server.join()
    t_sd.join()
    print("Python: All threads stopped. Exiting.")

