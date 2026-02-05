use std::net::UdpSocket;

fn main() -> std::io::Result<()> {
    // 1. Bind to a fixed port (Server)
    let socket = UdpSocket::bind("127.0.0.1:40000")?;
    println!("Simple Server listening on 127.0.0.1:40000");

    let mut buf = [0u8; 1500];
    loop {
        let (amt, src) = socket.recv_from(&mut buf)?;
        if amt < 16 { continue; } // Too short for SOME/IP header

        println!("Received {} bytes from {}", amt, src);

        // 2. Parse Header (Manually)
        // [ServiceID:2][MethodID:2][Length:4][ClientID:2][SessionID:2][Proto:1][Iface:1][MsgType:1][Ret:1]
        let service_id = u16::from_be_bytes([buf[0], buf[1]]);
        let method_id = u16::from_be_bytes([buf[2], buf[3]]);
        let msg_type = buf[14];

        println!("  Service: 0x{:04x}, Method: 0x{:04x}, Type: 0x{:02x}", service_id, method_id, msg_type);

        // 3. Send Response (if Request)
        if msg_type == 0x00 { // Request
            println!("  Sending Response...");
            
            // Construct Response Header
            // Same IDs, Change MsgType to 0x80 (Response)
            let mut res_header = [0u8; 16];
            res_header[0..2].copy_from_slice(&buf[0..2]); // Service ID
            res_header[2..4].copy_from_slice(&buf[2..4]); // Method ID
            
            // Payload: "OK" (2 bytes)
            // Length = Payload(2) + 8 = 10
            let length: u32 = 10;
            res_header[4..8].copy_from_slice(&length.to_be_bytes());
            
            res_header[8..12].copy_from_slice(&buf[8..12]); // Client/Session ID
            res_header[12] = 0x01; // Proto Ver
            res_header[13] = 0x01; // Iface Ver
            res_header[14] = 0x80; // Msg Type: Response
            res_header[15] = 0x00; // Return Code: OK

            let payload = b"OK";
            
            let mut response = Vec::new();
            response.extend_from_slice(&res_header);
            response.extend_from_slice(payload);

            socket.send_to(&response, src)?;
        }
    }
}
