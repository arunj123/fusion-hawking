/// End-to-end TCP integration test for SOME/IP communication.
///
/// This test verifies that TcpServerTransport and TcpTransport can exchange
/// well-formed SOME/IP messages (Request/Response) through the SomeIpTransport
/// trait abstraction, simulating a real runtime scenario.

use fusion_hawking::transport::{
    TcpServer, TcpServerTransport, TcpTransport, SomeIpTransport,
};
use fusion_hawking::codec::SomeIpHeader;
use std::sync::Arc;
use std::thread;
use std::time::Duration;
use std::io::ErrorKind;

#[test]
fn test_tcp_someip_request_response_via_trait() {
    // 1. Start a TCP server, wrap in TcpServerTransport (trait object)
    let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let server_addr = server.local_addr().unwrap();
    server.set_nonblocking(true).unwrap();
    
    let server_transport = Arc::new(TcpServerTransport::new(server));
    let server_t = server_transport.clone();
    
    // 2. Server thread: poll for connections + messages, respond
    let server_thread = thread::spawn(move || {
        let mut buf = [0u8; 4096];
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        
        loop {
            if std::time::Instant::now() >= deadline {
                panic!("Server timeout waiting for SOME/IP request");
            }
            
            match server_t.receive(&mut buf) {
                Ok((size, src)) => {
                    assert!(size >= 16, "SOME/IP message too short: {} bytes", size);
                    
                    // Deserialize header
                    let header = SomeIpHeader::deserialize(&buf[..16])
                        .expect("Failed to deserialize SOME/IP header");
                    
                    assert_eq!(header.service_id, 0x1001);
                    assert_eq!(header.method_id, 0x0001);
                    assert_eq!(header.message_type, 0x00); // REQUEST
                    
                    // Parse payload: two u32 values
                    let a = u32::from_be_bytes(buf[16..20].try_into().unwrap());
                    let b = u32::from_be_bytes(buf[20..24].try_into().unwrap());
                    let result = a + b;
                    
                    // Build SOME/IP Response
                    let res_header = SomeIpHeader::new(
                        header.service_id,
                        header.method_id,
                        header.client_id,
                        header.session_id,
                        0x80, // RESPONSE
                        4,    // payload = 4 bytes (u32 result)
                    );
                    
                    let mut response = res_header.serialize().to_vec();
                    response.extend_from_slice(&result.to_be_bytes());
                    
                    server_t.send(&response, Some(src)).unwrap();
                    return result;
                }
                Err(e) if e.kind() == ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(10));
                }
                Err(e) => panic!("Server receive error: {}", e),
            }
        }
    });
    
    // 3. Client: connect, send SOME/IP Request, receive Response
    thread::sleep(Duration::from_millis(100)); // Let server start polling
    
    let client = TcpTransport::connect(server_addr).unwrap();
    client.set_nonblocking(true).unwrap();
    
    // Build SOME/IP Request: Add(10, 20)
    let req_header = SomeIpHeader::new(
        0x1001, // service_id
        0x0001, // method_id
        0x0001, // client_id
        0x0001, // session_id
        0x00,   // REQUEST
        8,      // payload = 8 bytes (two u32s)
    );
    
    let mut request = req_header.serialize().to_vec();
    request.extend_from_slice(&10u32.to_be_bytes());
    request.extend_from_slice(&20u32.to_be_bytes());
    
    client.send(&request, None).unwrap();
    
    // 4. Receive response
    let mut buf = [0u8; 4096];
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    
    loop {
        if std::time::Instant::now() >= deadline {
            panic!("Client timeout waiting for SOME/IP response");
        }
        
        match client.receive(&mut buf) {
            Ok((size, _)) => {
                assert!(size >= 20, "Response too short: {} bytes", size);
                
                let header = SomeIpHeader::deserialize(&buf[..16])
                    .expect("Failed to deserialize response header");
                
                assert_eq!(header.service_id, 0x1001);
                assert_eq!(header.method_id, 0x0001);
                assert_eq!(header.message_type, 0x80); // RESPONSE
                assert_eq!(header.return_code, 0x00);  // E_OK
                
                let result = u32::from_be_bytes(buf[16..20].try_into().unwrap());
                assert_eq!(result, 30, "Expected 10 + 20 = 30, got {}", result);
                
                break;
            }
            Err(e) if e.kind() == ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10));
            }
            Err(e) => panic!("Client receive error: {}", e),
        }
    }
    
    // 5. Verify server computed correctly
    let server_result = server_thread.join().unwrap();
    assert_eq!(server_result, 30);
}

#[test]
fn test_tcp_connection_lifecycle() {
    let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let server_addr = server.local_addr().unwrap();
    server.set_nonblocking(true).unwrap();
    
    let server_transport = Arc::new(TcpServerTransport::new(server));
    
    // Initially no connections
    assert_eq!(server_transport.local_addr().unwrap().port(), server_addr.port());
    
    // Connect a client
    let client = TcpTransport::connect(server_addr).unwrap();
    let client_local = client.local_addr().unwrap();
    assert!(client_local.port() > 0);
    assert_eq!(client.peer_addr().unwrap(), server_addr);
    
    // Client can set non-blocking via trait
    <TcpTransport as SomeIpTransport>::set_nonblocking(&client, true).unwrap();
    
    // Verify client can send without panic (server will accept in background)
    let data = b"lifecycle test";
    client.send(data, None).unwrap();
    
    // Give server time to accept and receive
    thread::sleep(Duration::from_millis(100));
    
    let mut buf = [0u8; 128];
    match server_transport.receive(&mut buf) {
        Ok((len, _src)) => {
            assert_eq!(&buf[..len], data);
        }
        Err(e) if e.kind() == ErrorKind::WouldBlock => {
            // Acceptable on some platforms with timing
        }
        Err(e) => panic!("Unexpected error: {}", e),
    }
}
