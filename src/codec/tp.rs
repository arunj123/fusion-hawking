// use crate::codec::SomeIpHeader;

/// [PRS_SOMEIP_00705] SOME/IP-TP Header (4 bytes)
/// Located after the SOME/IP Header in TP messages.
/// Layout:
/// - Offset: 28 bits (Multiples of 16 bytes)
/// - Reserved: 3 bits
/// - More Segments: 1 bit
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TpHeader {
    pub offset: u32,
    pub more_segments: bool,
}

impl TpHeader {
    pub const HEADER_LENGTH: usize = 4;

    pub fn new(offset: u32, more_segments: bool) -> Self {
        TpHeader { offset, more_segments }
    }

    pub fn serialize(&self) -> [u8; 4] {
        let mut buffer = [0u8; 4];
        let offset_unit = self.offset / 16;
        let val = (offset_unit << 4) | (if self.more_segments { 1 } else { 0 });
        buffer.copy_from_slice(&val.to_be_bytes());
        buffer
    }

    pub fn deserialize(buffer: &[u8]) -> Result<Self, &'static str> {
        if buffer.len() < 4 {
            return Err("Buffer too small for TP header");
        }
        let val = u32::from_be_bytes([buffer[0], buffer[1], buffer[2], buffer[3]]);
        let offset_unit = val >> 4;
        let more_segments = (val & 0x01) == 1;
        
        Ok(TpHeader {
            offset: offset_unit * 16,
            more_segments,
        })
    }
}

/// Helper to segment a payload into chunks with TP headers.
pub fn segment_payload(payload: &[u8], max_payload_per_segment: usize) -> Vec<(TpHeader, Vec<u8>)> {
    // max_payload_per_segment must be multiple of 16 for alignment, 
    // but the last segment can be smaller.
    // However, the caller usually provides the MTU-based max size.
    // The TP offset unit is 16 bytes.
    // So all segments except last MUST be a multiple of 16 bytes.
    // We enforce this by rounding down max_payload_per_segment to nearest 16.
    
    let alignment = 16;
    let aligned_max = (max_payload_per_segment / alignment) * alignment;
    
    let mut segments = Vec::new();
    let total_len = payload.len();
    let mut cursor = 0;

    // Special case: empty payload
    if total_len == 0 {
        return vec![(TpHeader::new(0, false), Vec::new())];
    }

    while cursor < total_len {
        let remaining = total_len - cursor;
        let chunk_len = if remaining > aligned_max {
            aligned_max
        } else {
            remaining
        };

        // If we have remaining data after this chunk, set more=true
        let more = (cursor + chunk_len) < total_len;
        
        let chunk = payload[cursor..cursor+chunk_len].to_vec();
        
        segments.push((TpHeader::new(cursor as u32, more), chunk));
        
        cursor += chunk_len;
    }
    
    segments
}

/// Helper to reassemble a payload from stored segments.
/// Expects a map of Offset -> Data.
pub fn reassemble_payload(segments: &std::collections::BTreeMap<u32, Vec<u8>>) -> Result<Vec<u8>, &'static str> {
    let mut buffer = Vec::new();
    let mut next_offset = 0;
    
    for (offset, data) in segments {
        if *offset != next_offset {
            return Err("Missing segment / Gap in offsets");
        }
        buffer.extend_from_slice(data);
        next_offset += data.len() as u32;
    }
    
    Ok(buffer)
}

/// Manages reassembly of TP packets.
/// Key: (Message ID, Request ID) match [PRS_SOMEIP_00724]
/// Note: Real implementation should also track Source Address if possible, but this struct is generic.
pub struct TpReassembler {
    // Map<(MessageID, RequestID), Map<Offset, (Data, MoreFlag)>>
    buffers: std::collections::HashMap<(u32, u32), std::collections::BTreeMap<u32, (Vec<u8>, bool)>>,
}

impl TpReassembler {
    pub fn new() -> Self {
        TpReassembler {
            buffers: std::collections::HashMap::new(),
        }
    }

    /// Process a TP segment.
    /// Returns:
    /// - `Ok(Some(payload))` if assembly matches completion.
    /// - `Ok(None)` if stored but incomplete.
    /// - `Err` if invalid.
    pub fn process_segment(&mut self, message_id: u32, request_id: u32, tp_header: &TpHeader, payload: &[u8]) -> Result<Option<Vec<u8>>, &'static str> {
        let key = (message_id, request_id);
        
        let segments = self.buffers.entry(key).or_insert_with(std::collections::BTreeMap::new);
        segments.insert(tp_header.offset, (payload.to_vec(), tp_header.more_segments));
        
        // Check for completion
        // 1. Must have offset 0
        if !segments.contains_key(&0) {
            return Ok(None);
        }
        
        // 2. Iterate and verify continuity and end
        let mut expected_offset = 0;
        let mut complete = false;
        
        for (offset, (data, more)) in segments.iter() {
            if *offset != expected_offset {
                // Gap detected
                return Ok(None);
            }
            expected_offset += data.len() as u32;
            if !*more {
                complete = true;
                // Should be the last segment
                break;
            }
        }
        
        if complete {
            // Reassemble
            let mut buffer = Vec::new();
            for (_, (data, _)) in segments.iter() {
                buffer.extend_from_slice(data);
            }
            
            // Cleanup
            self.buffers.remove(&key);
            
            Ok(Some(buffer))
        } else {
            Ok(None)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn test_tp_header_serialization() {
        // Offset 16 (unit 1), detailed
        let tp = TpHeader::new(16, true);
        let bytes = tp.serialize();
        // 1 << 4 | 1 = 17 = 0x11
        // 00 00 00 11
        assert_eq!(bytes, [0x00, 0x00, 0x00, 0x11]);

        let tp2 = TpHeader::deserialize(&bytes).unwrap();
        assert_eq!(tp2.offset, 16);
        assert_eq!(tp2.more_segments, true);
    }
    
    #[test]
    fn test_segmentation() {
        let payload = vec![0u8; 40]; // 40 bytes
        // Max 16 bytes per segment
        let segments = segment_payload(&payload, 16);
        
        // Should be 3 segments:
        // 1. 0..16, More=1
        // 2. 16..32, More=1
        // 3. 32..40, More=0
        
        assert_eq!(segments.len(), 3);
        assert_eq!(segments[0].0.offset, 0);
        assert_eq!(segments[0].0.more_segments, true);
        assert_eq!(segments[0].1.len(), 16);
        
        assert_eq!(segments[1].0.offset, 16);
        assert_eq!(segments[1].0.more_segments, true);
        assert_eq!(segments[1].1.len(), 16);
        
        assert_eq!(segments[2].0.offset, 32);
        assert_eq!(segments[2].0.more_segments, false);
        assert_eq!(segments[2].1.len(), 8);
    }

    #[test]
    fn test_reassembly() {
        let payload: Vec<u8> = (0..100).collect();
        let segments = segment_payload(&payload, 30); // 30 isn't multiple of 16? 
        // Logic rounds down to 16. So aligned_max = 16.
        // 100 / 16 = 6 chunks of 16, 1 chunk of 4.
        
        let mut map = BTreeMap::new();
        for (header, data) in segments {
            map.insert(header.offset, data);
        }
        
        let reassembled = reassemble_payload(&map).expect("Reassembly failed");
        assert_eq!(reassembled, payload);
    }

    #[test]
    fn test_reassembly_missing_segment() {
        let payload: Vec<u8> = (0..50).collect();
        let segments = segment_payload(&payload, 32); // aligned to 32
        
        let mut map = BTreeMap::new();
        for (header, data) in segments {
            map.insert(header.offset, data);
        }
        
        map.remove(&0); // Remove first
        assert!(reassemble_payload(&map).is_err());
        
        // Reset
        let segments = segment_payload(&payload, 32);
        let mut map = BTreeMap::new();
        for (header, data) in segments {
             map.insert(header.offset, data);
        }
        map.remove(&32);
        // Note: Reassembly checks continuity. 0+32 = 32. 
        // But reassemble_payload only checks gaps between *provided* segments.
        // It does not know the total length. So if the last segment is missing, it returns Ok(partial).
        let res = reassemble_payload(&map);
        assert!(res.is_ok());
        assert_eq!(res.unwrap().len(), 32);
    }

    #[test]
    fn test_tp_reassembler_flow() {
        let mut reassembler = TpReassembler::new();
        let msg_id = 0x1234;
        let req_id = 0x5678;

        // payload = 0..40.
        // Seg 1: 0..16, more=1
        // Seg 2: 16..32, more=1
        // Seg 3: 32..40, more=0
        
        let s1 = (TpHeader::new(0, true), vec![0u8; 16]);
        let s2 = (TpHeader::new(16, true), vec![1u8; 16]);
        let s3 = (TpHeader::new(32, false), vec![2u8; 8]);
        
        // 1. Process S1 -> Incomplete
        let res = reassembler.process_segment(msg_id, req_id, &s1.0, &s1.1).unwrap();
        assert!(res.is_none());
        
        // 2. Process S3 (Out of order) -> Incomplete (missing S2)
        let res = reassembler.process_segment(msg_id, req_id, &s3.0, &s3.1).unwrap();
        assert!(res.is_none());
        
        // 3. Process S2 -> Complete!
        let res = reassembler.process_segment(msg_id, req_id, &s2.0, &s2.1).unwrap();
        assert!(res.is_some());
        
        let full_payload = res.unwrap();
        assert_eq!(full_payload.len(), 40);
        assert_eq!(full_payload[0..16], vec![0u8; 16]);
        assert_eq!(full_payload[16..32], vec![1u8; 16]);
        assert_eq!(full_payload[32..40], vec![2u8; 8]);
        
        // Buffer should be cleared
        assert!(reassembler.buffers.get(&(msg_id, req_id)).is_none());
    }
}
