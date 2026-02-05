use crate::codec::{SomeIpSerialize, SomeIpDeserialize};
use std::io::{Result, Write, Read};
use std::net::{Ipv4Addr, Ipv6Addr};

/// SD Option Type IDs as defined in AUTOSAR SOME/IP-SD Specification
pub mod option_types {
    pub const CONFIGURATION: u8 = 0x01;
    pub const LOAD_BALANCING: u8 = 0x02;
    pub const IPV4_ENDPOINT: u8 = 0x04;
    pub const IPV6_ENDPOINT: u8 = 0x06;
    pub const IPV4_MULTICAST: u8 = 0x14;
    pub const IPV6_MULTICAST: u8 = 0x16;
    pub const IPV4_SD_ENDPOINT: u8 = 0x24;
    pub const IPV6_SD_ENDPOINT: u8 = 0x26;
}

/// Transport Protocol identifiers
pub mod transport_protocol {
    pub const TCP: u8 = 0x06;
    pub const UDP: u8 = 0x11;
}

#[derive(Debug, Clone, PartialEq)]
pub enum SdOption {
    /// IPv4 Endpoint Option (Type 0x04)
    Ipv4Endpoint {
        address: Ipv4Addr,
        transport_proto: u8, // 0x06 TCP, 0x11 UDP
        port: u16,
    },
    /// IPv6 Endpoint Option (Type 0x06)
    Ipv6Endpoint {
        address: Ipv6Addr,
        transport_proto: u8,
        port: u16,
    },
    /// IPv4 Multicast Option (Type 0x14)
    Ipv4Multicast {
        address: Ipv4Addr,
        transport_proto: u8,
        port: u16,
    },
    /// IPv6 Multicast Option (Type 0x16)
    Ipv6Multicast {
        address: Ipv6Addr,
        transport_proto: u8,
        port: u16,
    },
    /// Configuration Option (Type 0x01) - contains configuration string
    Configuration {
        config_string: String,
    },
    /// Load Balancing Option (Type 0x02)
    LoadBalancing {
        priority: u16,
        weight: u16,
    },
    /// Unknown option type
    Unknown {
        length: u16,
        type_id: u8,
        data: Vec<u8>
    },
}

impl SdOption {
    /// Get the type ID for this option
    pub fn type_id(&self) -> u8 {
        match self {
            SdOption::Ipv4Endpoint { .. } => option_types::IPV4_ENDPOINT,
            SdOption::Ipv6Endpoint { .. } => option_types::IPV6_ENDPOINT,
            SdOption::Ipv4Multicast { .. } => option_types::IPV4_MULTICAST,
            SdOption::Ipv6Multicast { .. } => option_types::IPV6_MULTICAST,
            SdOption::Configuration { .. } => option_types::CONFIGURATION,
            SdOption::LoadBalancing { .. } => option_types::LOAD_BALANCING,
            SdOption::Unknown { type_id, .. } => *type_id,
        }
    }
}

impl SomeIpSerialize for SdOption {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        match self {
            SdOption::Ipv4Endpoint { address, transport_proto, port } => {
                // Length=9, Type=0x04
                // [Len:2][Type:1][Res:1][IPv4:4][Res:1][L4:1][Port:2]
                let len: u16 = 0x0009;
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[option_types::IPV4_ENDPOINT])?;
                writer.write_all(&[0x00])?; // Reserved
                writer.write_all(&address.octets())?;
                writer.write_all(&[0x00])?; // Reserved
                writer.write_all(&[*transport_proto])?;
                writer.write_all(&port.to_be_bytes())?;
            },
            SdOption::Ipv6Endpoint { address, transport_proto, port } => {
                // Length=21, Type=0x06
                let len: u16 = 0x0015;
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[option_types::IPV6_ENDPOINT])?;
                writer.write_all(&[0x00])?;
                writer.write_all(&address.octets())?;
                writer.write_all(&[0x00])?;
                writer.write_all(&[*transport_proto])?;
                writer.write_all(&port.to_be_bytes())?;
            },
            SdOption::Ipv4Multicast { address, transport_proto, port } => {
                // Same format as IPv4 Endpoint but Type=0x14
                let len: u16 = 0x0009;
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[option_types::IPV4_MULTICAST])?;
                writer.write_all(&[0x00])?;
                writer.write_all(&address.octets())?;
                writer.write_all(&[0x00])?;
                writer.write_all(&[*transport_proto])?;
                writer.write_all(&port.to_be_bytes())?;
            },
            SdOption::Ipv6Multicast { address, transport_proto, port } => {
                // Same format as IPv6 Endpoint but Type=0x16
                let len: u16 = 0x0015;
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[option_types::IPV6_MULTICAST])?;
                writer.write_all(&[0x00])?;
                writer.write_all(&address.octets())?;
                writer.write_all(&[0x00])?;
                writer.write_all(&[*transport_proto])?;
                writer.write_all(&port.to_be_bytes())?;
            },
            SdOption::Configuration { config_string } => {
                // Length = 1 (reserved) + string length
                let string_bytes = config_string.as_bytes();
                let len: u16 = (1 + string_bytes.len()) as u16;
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[option_types::CONFIGURATION])?;
                writer.write_all(&[0x00])?; // Reserved
                writer.write_all(string_bytes)?;
            },
            SdOption::LoadBalancing { priority, weight } => {
                // Length = 5 (1 reserved + 2 priority + 2 weight)
                let len: u16 = 0x0005;
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[option_types::LOAD_BALANCING])?;
                writer.write_all(&[0x00])?; // Reserved
                writer.write_all(&priority.to_be_bytes())?;
                writer.write_all(&weight.to_be_bytes())?;
            },
            SdOption::Unknown { length, type_id, data } => {
                writer.write_all(&length.to_be_bytes())?;
                writer.write_all(&[*type_id])?;
                writer.write_all(data)?;
            }
        }
        Ok(())
    }
}

impl SomeIpDeserialize for SdOption {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        let mut len_buf = [0u8; 2];
        reader.read_exact(&mut len_buf)?;
        let length = u16::from_be_bytes(len_buf);

        let mut type_buf = [0u8; 1];
        reader.read_exact(&mut type_buf)?;
        let type_id = type_buf[0];

        // Length indicates bytes AFTER the Type field
        let mut data = vec![0u8; length as usize];
        reader.read_exact(&mut data)?;

        match type_id {
            option_types::IPV4_ENDPOINT => {
                if data.len() < 9 {
                    return Ok(SdOption::Unknown { length, type_id, data });
                }
                // data[0] = Reserved, data[1..5] = IPv4, data[5] = Reserved, data[6] = Proto, data[7..9] = Port
                let addr = Ipv4Addr::new(data[1], data[2], data[3], data[4]);
                let transport = data[6];
                let port = u16::from_be_bytes([data[7], data[8]]);
                Ok(SdOption::Ipv4Endpoint {
                    address: addr,
                    transport_proto: transport,
                    port,
                })
            },
            option_types::IPV6_ENDPOINT => {
                if data.len() < 21 {
                    return Ok(SdOption::Unknown { length, type_id, data });
                }
                let mut ip_bytes = [0u8; 16];
                ip_bytes.copy_from_slice(&data[1..17]);
                let addr = Ipv6Addr::from(ip_bytes);
                let transport = data[18];
                let port = u16::from_be_bytes([data[19], data[20]]);
                Ok(SdOption::Ipv6Endpoint {
                    address: addr,
                    transport_proto: transport,
                    port,
                })
            },
            option_types::IPV4_MULTICAST => {
                if data.len() < 9 {
                    return Ok(SdOption::Unknown { length, type_id, data });
                }
                let addr = Ipv4Addr::new(data[1], data[2], data[3], data[4]);
                let transport = data[6];
                let port = u16::from_be_bytes([data[7], data[8]]);
                Ok(SdOption::Ipv4Multicast {
                    address: addr,
                    transport_proto: transport,
                    port,
                })
            },
            option_types::IPV6_MULTICAST => {
                if data.len() < 21 {
                    return Ok(SdOption::Unknown { length, type_id, data });
                }
                let mut ip_bytes = [0u8; 16];
                ip_bytes.copy_from_slice(&data[1..17]);
                let addr = Ipv6Addr::from(ip_bytes);
                let transport = data[18];
                let port = u16::from_be_bytes([data[19], data[20]]);
                Ok(SdOption::Ipv6Multicast {
                    address: addr,
                    transport_proto: transport,
                    port,
                })
            },
            option_types::CONFIGURATION => {
                // data[0] = Reserved, data[1..] = config string
                if data.is_empty() {
                    return Ok(SdOption::Configuration { config_string: String::new() });
                }
                let config_string = String::from_utf8_lossy(&data[1..]).to_string();
                Ok(SdOption::Configuration { config_string })
            },
            option_types::LOAD_BALANCING => {
                if data.len() < 5 {
                    return Ok(SdOption::Unknown { length, type_id, data });
                }
                // data[0] = Reserved, data[1..3] = priority, data[3..5] = weight
                let priority = u16::from_be_bytes([data[1], data[2]]);
                let weight = u16::from_be_bytes([data[3], data[4]]);
                Ok(SdOption::LoadBalancing { priority, weight })
            },
            _ => {
                Ok(SdOption::Unknown {
                    length,
                    type_id,
                    data,
                })
            }
        }
    }
}
