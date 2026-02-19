use std::convert::TryInto;

/// SOME/IP Message Types as defined in AUTOSAR SOME/IP Protocol Specification
/// [PRS_SOMEIP_00044]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum MessageType {
    /// Request expecting a response
    Request = 0x00,
    /// Request not expecting a response (fire-and-forget)
    RequestNoReturn = 0x01,
    /// Notification/Event (cyclic or on-change)
    Notification = 0x02,
    /// Request with Transport Protocol segmentation
    RequestWithTp = 0x20,
    /// Request no return with Transport Protocol segmentation
    RequestNoReturnWithTp = 0x21,
    /// Notification with Transport Protocol segmentation
    NotificationWithTp = 0x22,
    /// Response to a Request
    Response = 0x80,
    /// Error response
    Error = 0x81,
    /// Response with Transport Protocol segmentation
    ResponseWithTp = 0xA0,
    /// Error with Transport Protocol segmentation
    ErrorWithTp = 0xA1,
}

impl MessageType {
    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0x00 => Some(MessageType::Request),
            0x01 => Some(MessageType::RequestNoReturn),
            0x02 => Some(MessageType::Notification),
            0x20 => Some(MessageType::RequestWithTp),
            0x21 => Some(MessageType::RequestNoReturnWithTp),
            0x22 => Some(MessageType::NotificationWithTp),
            0x80 => Some(MessageType::Response),
            0x81 => Some(MessageType::Error),
            0xA0 => Some(MessageType::ResponseWithTp),
            0xA1 => Some(MessageType::ErrorWithTp),
            _ => None,
        }
    }
    
    pub fn is_request(&self) -> bool {
        matches!(self, MessageType::Request | MessageType::RequestNoReturn | 
                       MessageType::RequestWithTp | MessageType::RequestNoReturnWithTp)
    }
    
    pub fn is_response(&self) -> bool {
        matches!(self, MessageType::Response | MessageType::ResponseWithTp)
    }
    
    pub fn is_error(&self) -> bool {
        matches!(self, MessageType::Error | MessageType::ErrorWithTp)
    }
    
    pub fn is_notification(&self) -> bool {
        matches!(self, MessageType::Notification | MessageType::NotificationWithTp)
    }
    
    pub fn uses_tp(&self) -> bool {
        matches!(self, MessageType::RequestWithTp | MessageType::RequestNoReturnWithTp |
                       MessageType::NotificationWithTp | MessageType::ResponseWithTp | 
                       MessageType::ErrorWithTp)
    }
}

impl From<MessageType> for u8 {
    fn from(mt: MessageType) -> u8 {
        mt as u8
    }
}

/// SOME/IP Return Codes as defined in AUTOSAR SOME/IP Protocol Specification
/// [PRS_SOMEIP_00043]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ReturnCode {
    /// No error occurred
    Ok = 0x00,
    /// An unspecified error occurred
    NotOk = 0x01,
    /// The requested Service ID is unknown
    UnknownService = 0x02,
    /// The requested Method ID is unknown
    UnknownMethod = 0x03,
    /// Service/Method not ready
    NotReady = 0x04,
    /// Service/Method not reachable
    NotReachable = 0x05,
    /// Timeout on server side
    Timeout = 0x06,
    /// Protocol version mismatch
    WrongProtocolVersion = 0x07,
    /// Interface version mismatch
    WrongInterfaceVersion = 0x08,
    /// Malformed message
    MalformedMessage = 0x09,
    /// Wrong message type
    WrongMessageType = 0x0A,
    /// E2E protection check failed
    E2eRepeated = 0x0B,
    /// E2E protection wrong sequence
    E2eWrongSequence = 0x0C,
    /// E2E protection not available
    E2eNotAvailable = 0x0D,
    /// E2E protection no new data
    E2eNoNewData = 0x0E,
}

impl ReturnCode {
    pub fn from_u8(value: u8) -> Option<Self> {
        match value {
            0x00 => Some(ReturnCode::Ok),
            0x01 => Some(ReturnCode::NotOk),
            0x02 => Some(ReturnCode::UnknownService),
            0x03 => Some(ReturnCode::UnknownMethod),
            0x04 => Some(ReturnCode::NotReady),
            0x05 => Some(ReturnCode::NotReachable),
            0x06 => Some(ReturnCode::Timeout),
            0x07 => Some(ReturnCode::WrongProtocolVersion),
            0x08 => Some(ReturnCode::WrongInterfaceVersion),
            0x09 => Some(ReturnCode::MalformedMessage),
            0x0A => Some(ReturnCode::WrongMessageType),
            0x0B => Some(ReturnCode::E2eRepeated),
            0x0C => Some(ReturnCode::E2eWrongSequence),
            0x0D => Some(ReturnCode::E2eNotAvailable),
            0x0E => Some(ReturnCode::E2eNoNewData),
            _ => None,
        }
    }
    
    pub fn is_error(&self) -> bool {
        *self != ReturnCode::Ok
    }
}

impl From<ReturnCode> for u8 {
    fn from(rc: ReturnCode) -> u8 {
        rc as u8
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SomeIpHeader {
    /// [PRS_SOMEIP_00032] Service ID (16-bit)
    pub service_id: u16,
    /// [PRS_SOMEIP_00033] Method ID (16-bit)
    pub method_id: u16,
    /// [PRS_SOMEIP_00932] Length (32-bit, covers Request ID + Protocol Version + Interface Version + Message Type + Return Code + Payload)
    pub length: u32,
    /// [PRS_SOMEIP_00038] Client ID within Request ID
    pub client_id: u16,
    /// [PRS_SOMEIP_00038] Session ID within Request ID
    pub session_id: u16,
    /// [PRS_SOMEIP_00042] Protocol Version (8-bit) - MUST be 0x01
    pub protocol_version: u8,
    /// [PRS_SOMEIP_00043] Interface Version (8-bit)
    pub interface_version: u8,
    /// [PRS_SOMEIP_00044] Message Type (8-bit)
    pub message_type: u8,
    /// [PRS_SOMEIP_00045] Return Code (8-bit)
    pub return_code: u8,
}

impl SomeIpHeader {
    pub const HEADER_LENGTH: u32 = 16;
    pub const SOMEIP_PROTOCOL_VERSION: u8 = 0x01;
    pub const DEFAULT_INTERFACE_VERSION: u8 = 0x01;

    /// Create a new SOME/IP header with default interface version (0x01)
    pub fn new(service_id: u16, method_id: u16, client_id: u16, session_id: u16, message_type: u8, payload_len: u32) -> Self {
        Self::with_interface_version(service_id, method_id, client_id, session_id, message_type, payload_len, Self::DEFAULT_INTERFACE_VERSION)
    }
    
    /// Create a new SOME/IP header with configurable interface version
    pub fn with_interface_version(service_id: u16, method_id: u16, client_id: u16, session_id: u16, message_type: u8, payload_len: u32, interface_version: u8) -> Self {
        SomeIpHeader {
            service_id,
            method_id,
            length: payload_len + 8, // Length field covers Request ID to end of payload
            client_id,
            session_id,
            protocol_version: Self::SOMEIP_PROTOCOL_VERSION,
            interface_version,
            message_type,
            return_code: 0x00,
        }
    }
    
    /// Create a new SOME/IP header with a specific return code
    pub fn with_return_code(service_id: u16, method_id: u16, client_id: u16, session_id: u16, message_type: u8, payload_len: u32, return_code: u8) -> Self {
        let mut header = Self::new(service_id, method_id, client_id, session_id, message_type, payload_len);
        header.return_code = return_code;
        header
    }
    
    /// Get the message type as an enum
    pub fn message_type_enum(&self) -> Option<MessageType> {
        MessageType::from_u8(self.message_type)
    }
    
    /// Get the return code as an enum
    pub fn return_code_enum(&self) -> Option<ReturnCode> {
        ReturnCode::from_u8(self.return_code)
    }

    pub fn serialize(&self) -> [u8; 16] {
        let mut buffer = [0u8; 16];
        
        // [PRS_SOMEIP_00030] 16-Byte Header Layout
        
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

    #[cfg(feature = "packet-dump")]
    pub fn dump(&self, addr: std::net::SocketAddr) {
        let mt_str = match self.message_type {
            0x00 => "REQ",
            0x01 => "REQ_NO_RET",
            0x02 => "NOTIF",
            0x80 => "RESP",
            0x81 => "ERR",
            _ => "UNKNOWN",
        };
        log::debug!(target: "DUMP", "\n[DUMP] --- SOME/IP Message from {} ---", addr);
        log::debug!(target: "DUMP", "  [Header] Service:0x{:04X} Method:0x{:04X} Len:{} Client:0x{:04X} Session:0x{:04X}",
            self.service_id, self.method_id, self.length, self.client_id, self.session_id);
        log::debug!(target: "DUMP", "  [Header] Proto:v{} Iface:v{} Type:{} Return:0x{:02X}",
            self.protocol_version, self.interface_version, mt_str, self.return_code);
        log::debug!(target: "DUMP", "--------------------------------------\n");
    }
}
