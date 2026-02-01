#[cfg(test)]
mod tests {
    use crate::codec::header::SomeIpHeader;
    use crate::codec::traits::{SomeIpSerialize, SomeIpDeserialize};
    use std::io::Cursor;
    
    #[test]
    fn test_header_serialization() {
        let header = SomeIpHeader::new(0x1234, 0x5678, 0x0001, 0x0002, 0x00, 100);
        let bytes = header.serialize();
        
        assert_eq!(bytes.len(), 16);
        assert_eq!(bytes[0], 0x12);
        assert_eq!(bytes[1], 0x34);
        assert_eq!(bytes[4], 0x00);
        assert_eq!(bytes[7], 108); // 100 + 8
    }

    #[test]
    fn test_primitive_serialization() {
        let val: u32 = 0xDEADBEEF;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        assert_eq!(buf, vec![0xDE, 0xAD, 0xBE, 0xEF]);
        
        let mut reader = Cursor::new(buf);
        let decoded = u32::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, 0xDEADBEEF);
    }

    #[test]
    fn test_bool_serialization() {
        let val = true;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        assert_eq!(buf, vec![0x01]);
        
        let mut reader = Cursor::new(&buf);
        let decoded = bool::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, true);
        
        // Test false
        let mut buf2 = Vec::new();
        false.serialize(&mut buf2).unwrap();
        assert_eq!(buf2, vec![0x00]);
        
        let mut reader2 = Cursor::new(&buf2);
        let decoded2 = bool::deserialize(&mut reader2).unwrap();
        assert_eq!(decoded2, false);
    }
    
    #[test]
    fn test_u8_serialization() {
        let val: u8 = 0xFF;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        assert_eq!(buf, vec![0xFF]);
        
        let mut reader = Cursor::new(&buf);
        let decoded = u8::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, 0xFF);
    }
    
    #[test]
    fn test_u16_serialization() {
        let val: u16 = 0xABCD;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        assert_eq!(buf, vec![0xAB, 0xCD]); // Big endian
        
        let mut reader = Cursor::new(&buf);
        let decoded = u16::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, 0xABCD);
    }
    
    #[test]
    fn test_i8_serialization() {
        let val: i8 = -50;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        assert_eq!(buf, vec![0xCE]); // Two's complement
        
        let mut reader = Cursor::new(&buf);
        let decoded = i8::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, -50);
    }
    
    #[test]
    fn test_i16_serialization() {
        let val: i16 = -1000;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        // -1000 = 0xFC18 in two's complement
        assert_eq!(buf, vec![0xFC, 0x18]);
        
        let mut reader = Cursor::new(&buf);
        let decoded = i16::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, -1000);
    }
    
    #[test]
    fn test_i32_serialization() {
        let val: i32 = -100000;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        // -100000 = 0xFFFE7960 in two's complement
        assert_eq!(buf, vec![0xFF, 0xFE, 0x79, 0x60]);
        
        let mut reader = Cursor::new(&buf);
        let decoded = i32::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, -100000);
    }
    
    #[test]
    fn test_f32_serialization() {
        let val: f32 = 3.14159;
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        assert_eq!(buf.len(), 4);
        
        let mut reader = Cursor::new(&buf);
        let decoded = f32::deserialize(&mut reader).unwrap();
        assert!((decoded - 3.14159).abs() < 0.0001);
    }
    
    #[test]
    fn test_string_serialization() {
        let val = String::from("Hello SOME/IP!");
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        
        // String format: length (4 bytes) + utf-8 bytes
        assert_eq!(buf.len(), 4 + 14); // "Hello SOME/IP!" = 14 chars
        // Length field: 14 = 0x0000000E
        assert_eq!(buf[3], 14);
        
        let mut reader = Cursor::new(&buf);
        let decoded = String::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, "Hello SOME/IP!");
    }
    
    #[test]
    fn test_vec_i32_serialization() {
        let val: Vec<i32> = vec![1, 2, 3, -100, 1000];
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        
        // Vec format: length in bytes (4 bytes) + elements
        // 5 elements * 4 bytes = 20 bytes
        assert_eq!(buf.len(), 4 + 20);
        assert_eq!(buf[3], 20); // Length field
        
        let mut reader = Cursor::new(&buf);
        let decoded = Vec::<i32>::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, vec![1, 2, 3, -100, 1000]);
    }
    
    #[test]
    fn test_empty_vec_serialization() {
        let val: Vec<i32> = vec![];
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        
        // Empty vec: just length = 0
        assert_eq!(buf.len(), 4);
        assert_eq!(buf, vec![0, 0, 0, 0]);
        
        let mut reader = Cursor::new(&buf);
        let decoded = Vec::<i32>::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, Vec::<i32>::new());
    }
    
    #[test]
    fn test_empty_string_serialization() {
        let val = String::new();
        let mut buf = Vec::new();
        val.serialize(&mut buf).unwrap();
        
        assert_eq!(buf.len(), 4);
        assert_eq!(buf, vec![0, 0, 0, 0]);
        
        let mut reader = Cursor::new(&buf);
        let decoded = String::deserialize(&mut reader).unwrap();
        assert_eq!(decoded, "");
    }
    
    #[test]
    fn test_boundary_values() {
        // Test i32 min/max
        let min: i32 = i32::MIN;
        let max: i32 = i32::MAX;
        
        let mut buf_min = Vec::new();
        min.serialize(&mut buf_min).unwrap();
        let mut reader = Cursor::new(&buf_min);
        assert_eq!(i32::deserialize(&mut reader).unwrap(), i32::MIN);
        
        let mut buf_max = Vec::new();
        max.serialize(&mut buf_max).unwrap();
        let mut reader = Cursor::new(&buf_max);
        assert_eq!(i32::deserialize(&mut reader).unwrap(), i32::MAX);
    }
}
