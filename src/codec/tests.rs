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
    }
}
