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
    
    // =====================================================================
    // MessageType Tests - SOME/IP Protocol Compliance
    // =====================================================================
    
    #[test]
    fn test_message_type_values() {
        use crate::codec::header::MessageType;
        
        // Verify all message type enum values match SOME/IP spec
        assert_eq!(MessageType::Request as u8, 0x00);
        assert_eq!(MessageType::RequestNoReturn as u8, 0x01);
        assert_eq!(MessageType::Notification as u8, 0x02);
        assert_eq!(MessageType::RequestWithTp as u8, 0x20);
        assert_eq!(MessageType::RequestNoReturnWithTp as u8, 0x21);
        assert_eq!(MessageType::NotificationWithTp as u8, 0x22);
        assert_eq!(MessageType::Response as u8, 0x80);
        assert_eq!(MessageType::Error as u8, 0x81);
        assert_eq!(MessageType::ResponseWithTp as u8, 0xA0);
        assert_eq!(MessageType::ErrorWithTp as u8, 0xA1);
    }
    
    #[test]
    fn test_message_type_from_u8() {
        use crate::codec::header::MessageType;
        
        assert_eq!(MessageType::from_u8(0x00), Some(MessageType::Request));
        assert_eq!(MessageType::from_u8(0x80), Some(MessageType::Response));
        assert_eq!(MessageType::from_u8(0x81), Some(MessageType::Error));
        assert_eq!(MessageType::from_u8(0xFF), None); // Invalid
        assert_eq!(MessageType::from_u8(0x03), None); // Invalid gap
    }
    
    #[test]
    fn test_message_type_classification() {
        use crate::codec::header::MessageType;
        
        // Request types
        assert!(MessageType::Request.is_request());
        assert!(MessageType::RequestNoReturn.is_request());
        assert!(MessageType::RequestWithTp.is_request());
        
        // Response types
        assert!(MessageType::Response.is_response());
        assert!(MessageType::ResponseWithTp.is_response());
        
        // Error types
        assert!(MessageType::Error.is_error());
        assert!(MessageType::ErrorWithTp.is_error());
        
        // Notification types
        assert!(MessageType::Notification.is_notification());
        assert!(MessageType::NotificationWithTp.is_notification());
        
        // TP flag
        assert!(MessageType::RequestWithTp.uses_tp());
        assert!(!MessageType::Request.uses_tp());
    }
    
    // =====================================================================
    // ReturnCode Tests - SOME/IP Protocol Compliance
    // =====================================================================
    
    #[test]
    fn test_return_code_values() {
        use crate::codec::header::ReturnCode;
        
        // Verify all return code enum values match SOME/IP spec
        assert_eq!(ReturnCode::Ok as u8, 0x00);
        assert_eq!(ReturnCode::NotOk as u8, 0x01);
        assert_eq!(ReturnCode::UnknownService as u8, 0x02);
        assert_eq!(ReturnCode::UnknownMethod as u8, 0x03);
        assert_eq!(ReturnCode::NotReady as u8, 0x04);
        assert_eq!(ReturnCode::NotReachable as u8, 0x05);
        assert_eq!(ReturnCode::Timeout as u8, 0x06);
        assert_eq!(ReturnCode::WrongProtocolVersion as u8, 0x07);
        assert_eq!(ReturnCode::WrongInterfaceVersion as u8, 0x08);
        assert_eq!(ReturnCode::MalformedMessage as u8, 0x09);
        assert_eq!(ReturnCode::WrongMessageType as u8, 0x0A);
        assert_eq!(ReturnCode::E2eRepeated as u8, 0x0B);
        assert_eq!(ReturnCode::E2eWrongSequence as u8, 0x0C);
        assert_eq!(ReturnCode::E2eNotAvailable as u8, 0x0D);
        assert_eq!(ReturnCode::E2eNoNewData as u8, 0x0E);
    }
    
    #[test]
    fn test_return_code_from_u8() {
        use crate::codec::header::ReturnCode;
        
        assert_eq!(ReturnCode::from_u8(0x00), Some(ReturnCode::Ok));
        assert_eq!(ReturnCode::from_u8(0x01), Some(ReturnCode::NotOk));
        assert_eq!(ReturnCode::from_u8(0x0E), Some(ReturnCode::E2eNoNewData));
        assert_eq!(ReturnCode::from_u8(0x0F), None); // Invalid
        assert_eq!(ReturnCode::from_u8(0xFF), None); // Invalid
    }
    
    #[test]
    fn test_return_code_is_error() {
        use crate::codec::header::ReturnCode;
        
        assert!(!ReturnCode::Ok.is_error());
        assert!(ReturnCode::NotOk.is_error());
        assert!(ReturnCode::UnknownService.is_error());
        assert!(ReturnCode::Timeout.is_error());
    }
    
    // =====================================================================
    // Header Field Tests - SOME/IP Protocol Compliance
    // =====================================================================
    
    #[test]
    fn test_header_protocol_version() {
        // SOME/IP spec: protocol version must be 0x01
        assert_eq!(SomeIpHeader::SOMEIP_PROTOCOL_VERSION, 0x01);
        
        let header = SomeIpHeader::new(0x1234, 0x5678, 0x0001, 0x0001, 0x00, 0);
        assert_eq!(header.protocol_version, 0x01);
    }
    
    #[test]
    fn test_header_interface_version() {
        // Default interface version
        let header = SomeIpHeader::new(0x1234, 0x5678, 0x0001, 0x0001, 0x00, 0);
        assert_eq!(header.interface_version, 0x01);
        
        // Custom interface version
        let header2 = SomeIpHeader::with_interface_version(
            0x1234, 0x5678, 0x0001, 0x0001, 0x00, 0, 0x05
        );
        assert_eq!(header2.interface_version, 0x05);
    }
    
    #[test]
    fn test_header_length_field() {
        // Length = payload_len + 8 (includes Request ID to end)
        let header = SomeIpHeader::new(0x1234, 0x5678, 0x0001, 0x0001, 0x00, 100);
        assert_eq!(header.length, 108);
        
        // Zero payload
        let header2 = SomeIpHeader::new(0x1234, 0x5678, 0x0001, 0x0001, 0x00, 0);
        assert_eq!(header2.length, 8);
    }
    
    #[test]
    fn test_header_with_return_code() {
        use crate::codec::header::ReturnCode;
        
        let header = SomeIpHeader::with_return_code(
            0x1234, 0x5678, 0x0001, 0x0001, 0x80, 0, ReturnCode::UnknownMethod as u8
        );
        assert_eq!(header.return_code, 0x03);
        assert_eq!(header.return_code_enum(), Some(ReturnCode::UnknownMethod));
    }
    
    #[test]
    fn test_header_message_type_enum() {
        use crate::codec::header::MessageType;
        
        let header = SomeIpHeader::new(0x1234, 0x5678, 0x0001, 0x0001, 0x80, 0);
        assert_eq!(header.message_type_enum(), Some(MessageType::Response));
    }
    
    #[test]
    fn test_header_deserialize_error() {
        // Buffer too small
        let small_buffer = [0u8; 10];
        assert!(SomeIpHeader::deserialize(&small_buffer).is_err());
    }
    
    #[test]
    fn test_header_roundtrip() {
        use crate::codec::header::MessageType;
        
        let original = SomeIpHeader::with_return_code(
            0xABCD, 0x1234, 0x5678, 0x9ABC, 
            MessageType::Response as u8, 256, 0x00
        );
        
        let bytes = original.serialize();
        let deserialized = SomeIpHeader::deserialize(&bytes).unwrap();
        
        assert_eq!(deserialized.service_id, 0xABCD);
        assert_eq!(deserialized.method_id, 0x1234);
        assert_eq!(deserialized.client_id, 0x5678);
        assert_eq!(deserialized.session_id, 0x9ABC);
        assert_eq!(deserialized.length, 256 + 8);
        assert_eq!(deserialized.message_type, 0x80);
        assert_eq!(deserialized.return_code, 0x00);
    }
}
