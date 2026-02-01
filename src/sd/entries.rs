use crate::codec::{SomeIpSerialize, SomeIpDeserialize};
use std::io::{Result, Write, Read};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum EntryType {
    FindService = 0x00,
    OfferService = 0x01,
    SubscribeEventgroup = 0x06,
    SubscribeEventgroupAck = 0x07,
    Unknown = 0xFF,
}

impl From<u8> for EntryType {
    fn from(v: u8) -> Self {
        match v {
            0x00 => EntryType::FindService,
            0x01 => EntryType::OfferService,
            0x06 => EntryType::SubscribeEventgroup,
            0x07 => EntryType::SubscribeEventgroupAck,
            _ => EntryType::Unknown,
        }
    }
}

#[derive(Debug, Clone)]
pub struct SdEntry {
    pub entry_type: EntryType,
    pub index_1: u8,
    pub index_2: u8,
    pub number_of_opts_1: u8,
    pub number_of_opts_2: u8,
    pub service_id: u16,
    pub instance_id: u16,
    pub major_version: u8,
    pub ttl: u32, // 24 bits
    pub minor_version: u32, // For Service entries
    // OR eventgroup_id + counter for Eventgroup entries. simplify for MVP
}

impl SomeIpSerialize for SdEntry {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        writer.write_all(&[self.entry_type as u8])?;
        writer.write_all(&[self.index_1])?;
        writer.write_all(&[self.index_2])?;
        
        let opts_byte = (self.number_of_opts_1 << 4) | (self.number_of_opts_2 & 0x0F);
        writer.write_all(&[opts_byte])?;
        
        writer.write_all(&self.service_id.to_be_bytes())?;
        writer.write_all(&self.instance_id.to_be_bytes())?;
        writer.write_all(&[self.major_version])?;
        
        // TTL is 24 bits
        let ttl_bytes = self.ttl.to_be_bytes(); // 4 bytes [0, 1, 2, 3]
        writer.write_all(&ttl_bytes[1..4])?;
        
        writer.write_all(&self.minor_version.to_be_bytes())?;
        Ok(())
    }
}

// Deserialization requires implementing logic to parse the 16 byes.
impl SomeIpDeserialize for SdEntry {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        let mut buf = [0u8; 16];
        reader.read_exact(&mut buf)?;
        
        Ok(SdEntry {
            entry_type: buf[0].into(),
            index_1: buf[1],
            index_2: buf[2],
            number_of_opts_1: (buf[3] >> 4),
            number_of_opts_2: (buf[3] & 0x0F),
            service_id: u16::from_be_bytes([buf[4], buf[5]]),
            instance_id: u16::from_be_bytes([buf[6], buf[7]]),
            major_version: buf[8],
            ttl: u32::from_be_bytes([0, buf[9], buf[10], buf[11]]),
            minor_version: u32::from_be_bytes([buf[12], buf[13], buf[14], buf[15]]),
        })
    }
}
