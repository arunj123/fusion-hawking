use std::net::UdpSocket;
use std::time::Duration;

fn main() -> std::io::Result<()> {
    // 1. Bind to ephemeral port
    let socket = UdpSocket::bind("127.0.0.1:0")?;
    socket.set_read_timeout(Some(Duration::from_secs(2)))?;
    println!("Simple Client bound to {}", socket.local_addr()?);

    // 2. Construct Request (Manually)
    // Target: Service 0x1234, Method 0x0001
    let service_id: u16 = 0x1234;
    let method_id: u16 = 0x0001;
    let payload = b"Hello";
    let length: u32 = (payload.len() as u32) + 8;

    let mut header = [0u8; 16];
    header[0..2].copy_from_slice(&service_id.to_be_bytes());
    header[2..4].copy_from_slice(&method_id.to_be_bytes());
    header[4..8].copy_from_slice(&length.to_be_bytes());
    header[8..10].copy_from_slice(&0xDEADu16.to_be_bytes()); // Client ID
    header[10..12].copy_from_slice(&0xBEEFu16.to_be_bytes()); // Session ID
    header[12] = 0x01;
    header[13] = 0x01;
    header[14] = 0x00; // Request
    header[15] = 0x00;

    let mut msg = Vec::new();
    msg.extend_from_slice(&header);
    msg.extend_from_slice(payload);

    // 3. Send to Server (Fixed IP/Port)
    let server_addr = "127.0.0.1:40000";
    println!("Sending Request to {}", server_addr);
    socket.send_to(&msg, server_addr)?;

    // 4. Wait for Response
    let mut buf = [0u8; 1500];
    match socket.recv_from(&mut buf) {
        Ok((amt, src)) => {
            println!("Received {} bytes from {}", amt, src);
            if amt >= 16 {
                let msg_type = buf[14];
                if msg_type == 0x80 {
                    println!("Success: Got Response!");
                    if amt > 16 {
                         println!("Payload: {:?}", std::str::from_utf8(&buf[16..amt]).unwrap_or("Binary"));
                    }
                }
            }
        }
        Err(e) => println!("Error receiving: {}", e),
    }

    Ok(())
}
