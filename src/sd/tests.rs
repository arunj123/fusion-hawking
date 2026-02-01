#[cfg(test)]
mod tests {
    use crate::sd::entries::{SdEntry, EntryType};
    use std::net::{Ipv4Addr, Ipv6Addr};
    use crate::sd::options::SdOption;
    use crate::sd::packet::SdPacket;
    use crate::codec::{SomeIpSerialize, SomeIpDeserialize};

    #[test]
    fn test_sd_packet_serialization() {
        let entry = SdEntry {
            entry_type: EntryType::OfferService,
            index_1: 0, index_2: 0,
            number_of_opts_1: 0, number_of_opts_2: 0,
            service_id: 0x1234,
            instance_id: 0x5678,
            major_version: 1,
            ttl: 0x0000100,
            minor_version: 2,
        };
        
        let packet = SdPacket {
            flags: 0x80,
            entries: vec![entry],
            options: vec![],
        };
        
        let mut buf = Vec::new();
        packet.serialize(&mut buf).unwrap();
        
        // Verify minimal length
        // Flags(1) + Res(3) + EntLen(4) + Entry(16) + OptLen(4) = 28 bytes
        assert_eq!(buf.len(), 28);
        assert_eq!(buf[0], 0x80);
        // Entry Length = 16
        assert_eq!(buf[4], 0x00);
        assert_eq!(buf[7], 16);
    }

    #[test]
    fn test_sd_packet_round_trip() {
        let entry = SdEntry {
            entry_type: EntryType::OfferService,
            index_1: 0,
            index_2: 0,
            number_of_opts_1: 0,
            number_of_opts_2: 0,
            service_id: 0x1234,
            instance_id: 0x5678,
            major_version: 1,
            ttl: 0x00ABCDEF,
            minor_version: 2,
        };

        let opt_ipv4 = SdOption::Ipv4Endpoint {
            address: Ipv4Addr::new(192, 168, 1, 1),
            transport_proto: 0x11, // UDP
            port: 30490,
        };

        let opt_ipv6 = SdOption::Ipv6Endpoint {
            address: Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1),
            transport_proto: 0x06, // TCP
            port: 8080,
        };

        let packet = SdPacket {
            flags: 0x80,
            entries: vec![entry],
            options: vec![opt_ipv4, opt_ipv6],
        };

        let mut buf = Vec::new();
        packet.serialize(&mut buf).unwrap();

        let mut reader = &buf[..];
        let deserialized = SdPacket::deserialize(&mut reader).unwrap();

        assert_eq!(deserialized.flags, packet.flags);
        assert_eq!(deserialized.entries.len(), 1);
        assert_eq!(deserialized.options.len(), 2);

        let d_entry = &deserialized.entries[0];
        assert_eq!(d_entry.service_id, 0x1234);
        assert_eq!(d_entry.ttl, 0x00ABCDEF);

        match &deserialized.options[0] {
            SdOption::Ipv4Endpoint { address, port, .. } => {
                assert_eq!(*address, Ipv4Addr::new(192, 168, 1, 1));
                assert_eq!(*port, 30490);
            },
            _ => panic!("Expected IPv4 option first"),
        }
        
        match &deserialized.options[1] {
            SdOption::Ipv6Endpoint { address, port, .. } => {
                assert_eq!(*address, Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1));
                assert_eq!(*port, 8080);
            },
             _ => panic!("Expected IPv6 option second"),
        }
    }
}
