use fusion_hawking; 

// Include the generated code module
mod generated {
    include!(concat!(env!("CARGO_MANIFEST_DIR"), "/build/generated/rust/mod.rs"));
}

use generated::*;
use fusion_hawking::codec::{SomeIpSerialize, SomeIpDeserialize};
use std::io::Cursor;

#[test]
fn test_math_request_serialization() {
    let req = MathServiceAddRequest { a: 10, b: -20 };
    let mut buf = Vec::new();
    req.serialize(&mut buf).unwrap();
    
    // Check bytes (big endian)
    // 10 = 0x0000000A
    // -20 = 0xFFFFFFEC
    assert_eq!(buf, vec![0,0,0,10, 255,255,255,236]);
    
    let mut r = Cursor::new(buf);
    let req2 = MathServiceAddRequest::deserialize(&mut r).unwrap();
    assert_eq!(req2.a, 10);
    assert_eq!(req2.b, -20);
}

#[test]
fn test_string_request_serialization() {
    let req = StringServiceReverseRequest { text: "ABC".to_string() };
    let mut buf = Vec::new();
    req.serialize(&mut buf).unwrap();
    // 4 bytes len (3) + "ABC"
    assert_eq!(buf.len(), 7);
    assert_eq!(buf[3], 3);
    assert_eq!(&buf[4..], b"ABC");
    
    let mut r = Cursor::new(buf);
    let req2 = StringServiceReverseRequest::deserialize(&mut r).unwrap();
    assert_eq!(req2.text, "ABC");
}

#[test]
fn test_sort_request_serialization() {
    let req = SortServiceSortAscRequest { data: vec![1, -1] };
    let mut buf = Vec::new();
    req.serialize(&mut buf).unwrap();
    // Length (4 bytes) = 8 (2 * 4) assuming generator writes byte length
    // Elements: 1 (0x00000001), -1 (0xFFFFFFFF)
    let len = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]);
    assert_eq!(len, 8); 
    
    // Check elements
    assert_eq!(buf[4..8], [0, 0, 0, 1]);
    assert_eq!(buf[8..12], [255, 255, 255, 255]);

    let mut r = Cursor::new(buf);
    let req2 = SortServiceSortAscRequest::deserialize(&mut r).unwrap();
    assert_eq!(req2.data, vec![1, -1]);
}

#[test]
fn test_empty_list_serialization() {
    let req = SortServiceSortAscRequest { data: vec![] };
    let mut buf = Vec::new();
    req.serialize(&mut buf).unwrap();
    assert_eq!(buf.len(), 4);
    assert_eq!(buf, vec![0, 0, 0, 0]);
    
    let mut r = Cursor::new(buf);
    let req2 = SortServiceSortAscRequest::deserialize(&mut r).unwrap();
    assert!(req2.data.is_empty());
}
