import struct
import collections
from typing import List, Tuple, Dict, Optional

class TpHeader:
    """
    Represents the 4-byte TP Header.
    [Offset (28 bits) | Reserved (3 bits) | More Segments (1 bit)]
    Wait, my initial assumption was wrong above.
    According to Rust spec `impl TpHeader`:
       let val = (offset_unit << 4) | (if self.more_segments { 1 } else { 0 });
    This puts `more_segments` at bit 0.
    Standard (PRS_SOMEIP_00724):
    "The Offset field is 28 bits long... The unit is 16 bytes."
    "The Reserved field is 3 bits long"
    "The More Segments Flag is 1 bit long"
    BIT 31............................4..3...1...0
    [           Offset (28)          ][Res(3)][More(1)]
    
    So yes, `more_segments` is indeed at bit 0.
    """
    def __init__(self, offset: int, more_segments: bool):
        self.offset = offset
        self.more_segments = more_segments

    def serialize(self) -> bytes:
        offset_unit = self.offset // 16
        val = (offset_unit << 4) | (1 if self.more_segments else 0)
        return struct.pack(">I", val)

    @classmethod
    def deserialize(cls, data: bytes) -> 'TpHeader':
        val = struct.unpack(">I", data)[0]
        offset_unit = (val >> 4) & 0x0FFFFFFF
        more_segments = (val & 0x1) == 1
        return cls(offset_unit * 16, more_segments)

def segment_payload(payload: bytes, max_payload_per_segment: int) -> List[Tuple[TpHeader, bytes]]:
    """
    Splits payload into chunks with TP headers.
    max_payload_per_segment must be multiple of 16 (TP requirement for non-last segments).
    The last segment can be shorter.
    However, the length of TP segments (except last) should be multiple of 16.
    """
    # 1. Calculate usable size per segment
    # It must be multiple of 16.
    max_len = (max_payload_per_segment // 16) * 16
    if max_len == 0:
        raise ValueError("max_payload_per_segment too small (must be >= 16)")

    segments = []
    offset = 0
    total_len = len(payload)

    while offset < total_len:
        remaining = total_len - offset
        
        # Determine if this is the last segment
        if remaining > max_len:
            # Need more segments
            chunk_size = max_len
            more = True
        else:
            # Last segment
            chunk_size = remaining
            more = False
            
        chunk = payload[offset : offset+chunk_size]
        header = TpHeader(offset, more)
        segments.append((header, chunk))
        
        offset += chunk_size
        
    return segments

class TpReassembler:
    """
    Manages reassembly of TP segments.
    """
    def __init__(self):
        # Key: (service_id, method_id, client_id, session_id)
        # Value: { 
        #   "segments": { offset: bytes }, 
        #   "final_len": Optional[int], 
        #   "timer": float 
        # }
        self.assemblies: Dict[Tuple[int, int, int, int], Dict] = {}

    def process_segment(self, 
                       key: Tuple[int, int, int, int], 
                       tp_header: TpHeader, 
                       payload: bytes) -> Optional[bytes]:
        
        if key not in self.assemblies:
            self.assemblies[key] = {
                "segments": {},
                "final_len": None,
                "created_at": 0 
            }
            # print(f"DEBUG: New Assembly for {key}")
            
        state = self.assemblies[key]
        
        # Store segments
        state["segments"][tp_header.offset] = payload
        # print(f"DEBUG: Got segment for {key}: off={tp_header.offset} len={len(payload)} more={tp_header.more_segments}")
        
        # If this is the last segment, we know the total length
        if not tp_header.more_segments:
            state["final_len"] = tp_header.offset + len(payload)
            # print(f"DEBUG: Final Len detected for {key}: {state['final_len']}")
            
        # Check completeness
        if state["final_len"] is not None:
            final_len = state["final_len"]
            collected_len = sum(len(c) for c in state["segments"].values())
            
            # Fast check: Do we have enough bytes?
            if collected_len == final_len:
                # Detailed check for gaps
                sorted_offsets = sorted(state["segments"].keys())
                current_off = 0
                full_payload = bytearray()
                
                for off in sorted_offsets:
                    if off != current_off:
                        # Gap detected
                        return None
                    chunk = state["segments"][off]
                    full_payload.extend(chunk)
                    current_off += len(chunk)
                
                # If we are here, reassembly complete
                del self.assemblies[key]
                return bytes(full_payload)
                
        return None
