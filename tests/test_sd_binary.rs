use fusion_hawking::codec::SomeIpSerialize;
use fusion_hawking::sd::packet::SdPacket;
use fusion_hawking::sd::entries::{SdEntry, EntryType};
use fusion_hawking::sd::options::SdOption;
use std::net::Ipv4Addr;

#[test]
/// [PRS_SOMEIPSD_00016] Verify SD Packet Layout
fn test_sd_packet_binary_layout() {
    let entry = SdEntry {
        entry_type: EntryType::OfferService,
        index_1: 0,
        index_2: 0,
        number_of_opts_1: 1,
        number_of_opts_2: 0,
        service_id: 0x1234,
        instance_id: 1,
        major_version: 1,
        ttl: 0xFFFFFF,
        minor_version: 10,
    };

    let option = SdOption::Ipv4Endpoint {
        address: Ipv4Addr::new(127, 0, 0, 1),
        transport_proto: 0x11, // UDP
        port: 30500,
    };

    let packet = SdPacket {
        flags: 0x80,
        entries: vec![entry],
        options: vec![option],
    };

    let mut buf = Vec::new();
    packet.serialize(&mut buf).unwrap();

    // Layout:
    // [0..4] SD Header (Flags:1, Res:3)
    assert_eq!(buf[0], 0x80);
    assert_eq!(buf[1..4], [0, 0, 0]);

    // [4..8] Entries Len (Should be 16 for 1 entry)
    assert_eq!(buf[4..8], [0, 0, 0, 16]);

    // [8..24] Entry (16 bytes)
    assert_eq!(buf[8], 0x01); // Offer
    assert_eq!(buf[9], 0);    // Index 1
    assert_eq!(buf[11], 0x10); // NumOpts (1 << 4 | 0)
    assert_eq!(buf[12..14], [0x12, 0x34]); // SvcID

    // [24..28] Options Len (CRITICAL: Should be 12)
    assert_eq!(buf[24..28], [0, 0, 0, 12]);

    // [28..30] Option Len (10)
    assert_eq!(buf[28..30], [0, 10]);

    // [30] Option Type (0x04)
    assert_eq!(buf[30], 0x04);
    
    // Total size
    assert_eq!(buf.len(), 4 + 4 + 16 + 4 + 12);
}
