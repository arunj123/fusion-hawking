use crate::codec::{SomeIpSerialize, SomeIpDeserialize, SomeIpHeader};
use std::io::{Result, Write, Read, Cursor};
use std::sync::Arc;
use crate::transport::{UdpTransport, SomeIpTransport};
use std::net::SocketAddr;

#[derive(Debug, Clone, PartialEq)]
pub struct SortData {
    pub values: Vec<i32>,
}
impl SomeIpSerialize for SortData {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.values.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for SortData {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(SortData {
            values: <Vec<i32>>::deserialize(reader)?,
        })
    }
}

// --- Service: MathService (ID: 0x1001) ---
#[derive(Debug, Clone, PartialEq)]
pub struct MathServiceAddRequest {
    pub a: i32,
    pub b: i32,
}
impl SomeIpSerialize for MathServiceAddRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.a.serialize(writer)?;
        self.b.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for MathServiceAddRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(MathServiceAddRequest {
            a: <i32>::deserialize(reader)?,
            b: <i32>::deserialize(reader)?,
        })
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct MathServiceAddResponse {
    pub result: i32,
}
impl SomeIpSerialize for MathServiceAddResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for MathServiceAddResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(MathServiceAddResponse {
            result: <i32>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MathServiceSubRequest {
    pub a: i32,
    pub b: i32,
}
impl SomeIpSerialize for MathServiceSubRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.a.serialize(writer)?;
        self.b.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for MathServiceSubRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(MathServiceSubRequest {
            a: <i32>::deserialize(reader)?,
            b: <i32>::deserialize(reader)?,
        })
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct MathServiceSubResponse {
    pub result: i32,
}
impl SomeIpSerialize for MathServiceSubResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for MathServiceSubResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(MathServiceSubResponse {
            result: <i32>::deserialize(reader)?,
        })
    }
}

pub trait MathServiceProvider: Send + Sync {
    fn add(&self, a: i32, b: i32) -> i32;
    fn sub(&self, a: i32, b: i32) -> i32;
}
pub struct MathServiceServer<T: MathServiceProvider> {
    provider: Arc<T>,
}
impl<T: MathServiceProvider> MathServiceServer<T> {
    pub fn new(provider: Arc<T>) -> Self { Self { provider } }
}
impl<T: MathServiceProvider> crate::runtime::RequestHandler for MathServiceServer<T> {
    fn service_id(&self) -> u16 { 4097 }
    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>> {
        if header.service_id != 4097 { return None; }
        match header.method_id {
            1 => {
                let mut cursor = Cursor::new(payload);
                if let Ok(req) = MathServiceAddRequest::deserialize(&mut cursor) {
                    let result = self.provider.add(req.a, req.b);
                    let resp = MathServiceAddResponse { result };
                    let mut out = Vec::new();
                    resp.serialize(&mut out).ok()?;
                    Some(out)
                } else { None }
            },
            2 => {
                let mut cursor = Cursor::new(payload);
                if let Ok(req) = MathServiceSubRequest::deserialize(&mut cursor) {
                    let result = self.provider.sub(req.a, req.b);
                    let resp = MathServiceSubResponse { result };
                    let mut out = Vec::new();
                    resp.serialize(&mut out).ok()?;
                    Some(out)
                } else { None }
            },
            _ => None
        }
    }
}
pub struct MathServiceClient {
    transport: Arc<UdpTransport>,
    target: SocketAddr,
}
impl crate::runtime::ServiceClient for MathServiceClient {
    const SERVICE_ID: u16 = 4097;
    fn new(transport: Arc<UdpTransport>, target: SocketAddr) -> Self { Self { transport, target } }
}
impl MathServiceClient {
    pub fn add(&self, a: i32, b: i32) -> std::io::Result<i32> {
        let req = MathServiceAddRequest { a, b };
        let mut payload = Vec::new();
        req.serialize(&mut payload)?;
        let header = SomeIpHeader::new(4097, 1, 0x1234, 0x01, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend(payload);
        self.transport.send(&msg, Some(self.target))?;
        Ok(Default::default())
    }
    pub fn sub(&self, a: i32, b: i32) -> std::io::Result<i32> {
        let req = MathServiceSubRequest { a, b };
        let mut payload = Vec::new();
        req.serialize(&mut payload)?;
        let header = SomeIpHeader::new(4097, 2, 0x1234, 0x01, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend(payload);
        self.transport.send(&msg, Some(self.target))?;
        Ok(Default::default())
    }
}
// --- Service: StringService (ID: 0x2001) ---
#[derive(Debug, Clone, PartialEq)]
pub struct StringServiceReverseRequest {
    pub text: String,
}
impl SomeIpSerialize for StringServiceReverseRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.text.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for StringServiceReverseRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(StringServiceReverseRequest {
            text: <String>::deserialize(reader)?,
        })
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct StringServiceReverseResponse {
    pub result: String,
}
impl SomeIpSerialize for StringServiceReverseResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for StringServiceReverseResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(StringServiceReverseResponse {
            result: <String>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct StringServiceUppercaseRequest {
    pub text: String,
}
impl SomeIpSerialize for StringServiceUppercaseRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.text.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for StringServiceUppercaseRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(StringServiceUppercaseRequest {
            text: <String>::deserialize(reader)?,
        })
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct StringServiceUppercaseResponse {
    pub result: String,
}
impl SomeIpSerialize for StringServiceUppercaseResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for StringServiceUppercaseResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(StringServiceUppercaseResponse {
            result: <String>::deserialize(reader)?,
        })
    }
}

pub trait StringServiceProvider: Send + Sync {
    fn reverse(&self, text: String) -> String;
    fn uppercase(&self, text: String) -> String;
}
pub struct StringServiceServer<T: StringServiceProvider> {
    provider: Arc<T>,
}
impl<T: StringServiceProvider> StringServiceServer<T> {
    pub fn new(provider: Arc<T>) -> Self { Self { provider } }
}
impl<T: StringServiceProvider> crate::runtime::RequestHandler for StringServiceServer<T> {
    fn service_id(&self) -> u16 { 8193 }
    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>> {
        if header.service_id != 8193 { return None; }
        match header.method_id {
            1 => {
                let mut cursor = Cursor::new(payload);
                if let Ok(req) = StringServiceReverseRequest::deserialize(&mut cursor) {
                    let result = self.provider.reverse(req.text);
                    let resp = StringServiceReverseResponse { result };
                    let mut out = Vec::new();
                    resp.serialize(&mut out).ok()?;
                    Some(out)
                } else { None }
            },
            2 => {
                let mut cursor = Cursor::new(payload);
                if let Ok(req) = StringServiceUppercaseRequest::deserialize(&mut cursor) {
                    let result = self.provider.uppercase(req.text);
                    let resp = StringServiceUppercaseResponse { result };
                    let mut out = Vec::new();
                    resp.serialize(&mut out).ok()?;
                    Some(out)
                } else { None }
            },
            _ => None
        }
    }
}
pub struct StringServiceClient {
    transport: Arc<UdpTransport>,
    target: SocketAddr,
}
impl crate::runtime::ServiceClient for StringServiceClient {
    const SERVICE_ID: u16 = 8193;
    fn new(transport: Arc<UdpTransport>, target: SocketAddr) -> Self { Self { transport, target } }
}
impl StringServiceClient {
    pub fn reverse(&self, text: String) -> std::io::Result<String> {
        let req = StringServiceReverseRequest { text };
        let mut payload = Vec::new();
        req.serialize(&mut payload)?;
        let header = SomeIpHeader::new(8193, 1, 0x1234, 0x01, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend(payload);
        self.transport.send(&msg, Some(self.target))?;
        Ok(Default::default())
    }
    pub fn uppercase(&self, text: String) -> std::io::Result<String> {
        let req = StringServiceUppercaseRequest { text };
        let mut payload = Vec::new();
        req.serialize(&mut payload)?;
        let header = SomeIpHeader::new(8193, 2, 0x1234, 0x01, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend(payload);
        self.transport.send(&msg, Some(self.target))?;
        Ok(Default::default())
    }
}
// --- Service: SortService (ID: 0x3001) ---
#[derive(Debug, Clone, PartialEq)]
pub struct SortServiceSortAscRequest {
    pub data: Vec<i32>,
}
impl SomeIpSerialize for SortServiceSortAscRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.data.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for SortServiceSortAscRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(SortServiceSortAscRequest {
            data: <Vec<i32>>::deserialize(reader)?,
        })
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct SortServiceSortAscResponse {
    pub result: Vec<i32>,
}
impl SomeIpSerialize for SortServiceSortAscResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for SortServiceSortAscResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(SortServiceSortAscResponse {
            result: <Vec<i32>>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct SortServiceSortDescRequest {
    pub data: Vec<i32>,
}
impl SomeIpSerialize for SortServiceSortDescRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.data.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for SortServiceSortDescRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(SortServiceSortDescRequest {
            data: <Vec<i32>>::deserialize(reader)?,
        })
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct SortServiceSortDescResponse {
    pub result: Vec<i32>,
}
impl SomeIpSerialize for SortServiceSortDescResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}
impl SomeIpDeserialize for SortServiceSortDescResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(SortServiceSortDescResponse {
            result: <Vec<i32>>::deserialize(reader)?,
        })
    }
}

pub trait SortServiceProvider: Send + Sync {
    fn sort_asc(&self, data: Vec<i32>) -> Vec<i32>;
    fn sort_desc(&self, data: Vec<i32>) -> Vec<i32>;
}
pub struct SortServiceServer<T: SortServiceProvider> {
    provider: Arc<T>,
}
impl<T: SortServiceProvider> SortServiceServer<T> {
    pub fn new(provider: Arc<T>) -> Self { Self { provider } }
}
impl<T: SortServiceProvider> crate::runtime::RequestHandler for SortServiceServer<T> {
    fn service_id(&self) -> u16 { 12289 }
    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>> {
        if header.service_id != 12289 { return None; }
        match header.method_id {
            1 => {
                let mut cursor = Cursor::new(payload);
                if let Ok(req) = SortServiceSortAscRequest::deserialize(&mut cursor) {
                    let result = self.provider.sort_asc(req.data);
                    let resp = SortServiceSortAscResponse { result };
                    let mut out = Vec::new();
                    resp.serialize(&mut out).ok()?;
                    Some(out)
                } else { None }
            },
            2 => {
                let mut cursor = Cursor::new(payload);
                if let Ok(req) = SortServiceSortDescRequest::deserialize(&mut cursor) {
                    let result = self.provider.sort_desc(req.data);
                    let resp = SortServiceSortDescResponse { result };
                    let mut out = Vec::new();
                    resp.serialize(&mut out).ok()?;
                    Some(out)
                } else { None }
            },
            _ => None
        }
    }
}
pub struct SortServiceClient {
    transport: Arc<UdpTransport>,
    target: SocketAddr,
}
impl crate::runtime::ServiceClient for SortServiceClient {
    const SERVICE_ID: u16 = 12289;
    fn new(transport: Arc<UdpTransport>, target: SocketAddr) -> Self { Self { transport, target } }
}
impl SortServiceClient {
    pub fn sort_asc(&self, data: Vec<i32>) -> std::io::Result<Vec<i32>> {
        let req = SortServiceSortAscRequest { data };
        let mut payload = Vec::new();
        req.serialize(&mut payload)?;
        let header = SomeIpHeader::new(12289, 1, 0x1234, 0x01, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend(payload);
        self.transport.send(&msg, Some(self.target))?;
        Ok(Default::default())
    }
    pub fn sort_desc(&self, data: Vec<i32>) -> std::io::Result<Vec<i32>> {
        let req = SortServiceSortDescRequest { data };
        let mut payload = Vec::new();
        req.serialize(&mut payload)?;
        let header = SomeIpHeader::new(12289, 2, 0x1234, 0x01, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend(payload);
        self.transport.send(&msg, Some(self.target))?;
        Ok(Default::default())
    }
}