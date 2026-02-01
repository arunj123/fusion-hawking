use crate::codec::{SomeIpSerialize, SomeIpDeserialize};
use std::io::{Result, Write, Read};
use std::net::{Ipv4Addr, Ipv6Addr};

#[derive(Debug, Clone)]
pub enum SdOption {
    Ipv4Endpoint {
        address: Ipv4Addr,
        transport_proto: u8, // 0x06 TCP, 0x11 UDP
        port: u16,
    },
    Ipv6Endpoint {
        address: Ipv6Addr,
        transport_proto: u8,
        port: u16,
    },
    Unknown {
        length: u16,
        type_id: u8,
        data: Vec<u8>
    },
}

impl SomeIpSerialize for SdOption {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        match self {
            SdOption::Ipv4Endpoint { address, transport_proto, port } => {
                let len: u16 = 0x0009; // Length field is 16 bits. 9 bytes payload after Len.
                // Format: [Len(2)][Type(1)][Res(1)][IPv4(4)][Res(1)][L4(1)][Port(2)] = 2+1+1+4+1+1+2 = 12 bytes total. Length excludes Len field(2) + Type(1). So payload is 9 bytes. Wait.
                // Spec: Length field indicates bytes starting after Type field.
                // Total option is: Len(2) + Type(1) + Data.
                // IPv4 Option: Length=0x0009. Type=0x04.
                // [Len:2=0009] [Type:1=04] [Res:1] [IPv4:4] [Res:1] [L4:1] [Port:2]
                
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[0x04])?; // Type IPv4
                writer.write_all(&[0x00])?; // Res
                writer.write_all(&address.octets())?;
                writer.write_all(&[0x00])?; // Res
                writer.write_all(transport_proto.to_be_bytes().as_slice())?;
                writer.write_all(&port.to_be_bytes())?;
            },
            SdOption::Ipv6Endpoint { address, transport_proto, port } => {
                let len: u16 = 0x0015; // 21 bytes
                writer.write_all(&len.to_be_bytes())?;
                writer.write_all(&[0x06])?; // Type IPv6
                writer.write_all(&[0x00])?;
                writer.write_all(&address.octets())?;
                writer.write_all(&[0x00])?;
                writer.write_all(transport_proto.to_be_bytes().as_slice())?;
                writer.write_all(&port.to_be_bytes())?;
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

        // Length indicates bytes AFTER the Type field.
        // So we need to read `length` bytes.
        let mut data = vec![0u8; length as usize];
        reader.read_exact(&mut data)?;

        match type_id {
            0x04 => { // IPv4 Endpoint
                if data.len() < 9 {
                     return Ok(SdOption::Unknown { length, type_id, data });
                }
                // data[0] is Res
                // data[1..5] is IPv4
                // data[5] is Res
                // data[6] is Proto
                // data[7..9] is Port
                let addr = Ipv4Addr::new(data[1], data[2], data[3], data[4]);
                let transport = data[6];
                let port = u16::from_be_bytes([data[7], data[8]]);
                Ok(SdOption::Ipv4Endpoint {
                    address: addr,
                    transport_proto: transport,
                    port,
                })
            },
            0x06 => { // IPv6 Endpoint
                 if data.len() < 21 {
                     return Ok(SdOption::Unknown { length, type_id, data });
                }
                // data[0] is Res
                // data[1..17] is IPv6
                // data[17] is Res
                // data[18] is Proto
                // data[19..21] is Port
                
                // Construct u8 array for IPv6
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
