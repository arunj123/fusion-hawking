use std::convert::TryInto;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SomeIpHeader {
    pub service_id: u16,
    pub method_id: u16,
    pub length: u32,
    pub client_id: u16,
    pub session_id: u16,
    pub protocol_version: u8,
    pub interface_version: u8,
    pub message_type: u8,
    pub return_code: u8,
}

impl SomeIpHeader {
    pub const HEADER_LENGTH: u32 = 16;
    pub const SOMEIP_PROTOCOL_VERSION: u8 = 0x01;

    pub fn new(service_id: u16, method_id: u16, client_id: u16, session_id: u16, message_type: u8, payload_len: u32) -> Self {
        SomeIpHeader {
            service_id,
            method_id,
            length: payload_len + 8, // Length field covers Request ID to end of payload. Request ID (4) + Proto/Int Ver/MsgType/RetCode (4) = 8
            client_id,
            session_id,
            protocol_version: Self::SOMEIP_PROTOCOL_VERSION,
            interface_version: 0x01, // Default, should be configurable
            message_type,
            return_code: 0x00,
        }
    }

    pub fn serialize(&self) -> [u8; 16] {
        let mut buffer = [0u8; 16];
        
        // Message ID (Service ID + Method ID)
        buffer[0..2].copy_from_slice(&self.service_id.to_be_bytes());
        buffer[2..4].copy_from_slice(&self.method_id.to_be_bytes());
        
        // Length
        buffer[4..8].copy_from_slice(&self.length.to_be_bytes());
        
        // Request ID (Client ID + Session ID)
        buffer[8..10].copy_from_slice(&self.client_id.to_be_bytes());
        buffer[10..12].copy_from_slice(&self.session_id.to_be_bytes());
        
        // Protocol Version
        buffer[12] = self.protocol_version;
        
        // Interface Version
        buffer[13] = self.interface_version;
        
        // Message Type
        buffer[14] = self.message_type;
        
        // Return Code
        buffer[15] = self.return_code;
        
        buffer
    }

    pub fn deserialize(buffer: &[u8]) -> Result<Self, &'static str> {
        if buffer.len() < 16 {
            return Err("Buffer too small for SOME/IP header");
        }

        Ok(SomeIpHeader {
            service_id: u16::from_be_bytes(buffer[0..2].try_into().unwrap()),
            method_id: u16::from_be_bytes(buffer[2..4].try_into().unwrap()),
            length: u32::from_be_bytes(buffer[4..8].try_into().unwrap()),
            client_id: u16::from_be_bytes(buffer[8..10].try_into().unwrap()),
            session_id: u16::from_be_bytes(buffer[10..12].try_into().unwrap()),
            protocol_version: buffer[12],
            interface_version: buffer[13],
            message_type: buffer[14],
            return_code: buffer[15],
        })
    }
}
