use fusion_hawking::codec::{SomeIpHeader, SomeIpSerialize, SomeIpDeserialize};
use fusion_hawking::transport::{UdpTransport, SomeIpTransport};
use fusion_hawking::runtime::ThreadPool;
use fusion_hawking::generated::{RustMathRequest, RustMathResponse, PyStringRequest, CppSortRequest};
use fusion_hawking::{ServiceDiscovery}; 
use std::net::{SocketAddr}; // Removed UdpSocket
use std::sync::{Arc}; // Removed Mutex
use std::io::Cursor;
use std::thread;
use std::time::Duration;

const MATH_PORT: u16 = 30501;
// Removed unused ports

fn main() {
    println!("Starting Rust Demo App (Math Service)...");

    // 1. Start Service Discovery
    // We need a separate transport for SD (ephemeral port for sending)
    let sd_multicast: SocketAddr = "224.0.0.1:30490".parse().unwrap();
    let sd_bind: SocketAddr = "0.0.0.0:0".parse().unwrap();
    let sd_transport = UdpTransport::new(sd_bind).expect("Failed to bind SD transport");
    let mut sd = ServiceDiscovery::new(sd_transport, sd_multicast);
    
    // Offer Math Service (0x1001, Instance 1) on port MATH_PORT (UDP 0x11)
    println!("Rust Service: Offering Service 0x1001 on port {}", MATH_PORT);
    sd.offer_service(0x1001, 1, 1, 0, MATH_PORT, 0x11);
    
    // Run SD in background thread
    thread::spawn(move || {
        loop {
            sd.poll();
            thread::sleep(Duration::from_millis(10));
        }
    });

    let pool = ThreadPool::new(4);
    
    // 2. Start Service Transport
    let addr: SocketAddr = format!("127.0.0.1:{}", MATH_PORT).parse().unwrap();
    let transport = Arc::new(UdpTransport::new(addr).expect("Failed to bind Service transport"));
    
    let t_clone = transport.clone();
    
    // Server Loop
    pool.execute(move || {
        let mut buf = [0u8; 1500];
        loop {
            match t_clone.receive(&mut buf) {
                Ok((size, src)) => {
                    // println!("Rust Service received {} bytes from {}", size, src);
                    let mut cursor = Cursor::new(&buf[..size]);
                    
                    if let Ok(header) = SomeIpHeader::deserialize(&buf[..16]) {
                        // Check Service ID / Method ID
                        // Assume Math Service ID = 0x1001, Method = 0x01
                         if header.service_id == 0x1001 && header.method_id == 0x0001 {
                             // Correctly position cursor after header
                             cursor.set_position(16);
                             
                             if let Ok(req) = RustMathRequest::deserialize(&mut cursor) {
                                 println!("Rust Service: Req op={}, a={}, b={}", req.op, req.a, req.b);
                                 
                                 let res_val = match req.op {
                                     1 => req.a + req.b,
                                     2 => req.a - req.b,
                                     3 => req.a * req.b,
                                     _ => 0,
                                 };
                                 
                                 let resp = RustMathResponse { result: res_val };
                                 let mut payload = Vec::new();
                                 resp.serialize(&mut payload).unwrap();
                                 
                                 // Send Response (Flip Message Type to Response 0x80)
                                 let res_header = SomeIpHeader::new(
                                     header.service_id, header.method_id, 
                                     header.client_id, header.session_id, 
                                     0x80, payload.len() as u32
                                 );
                                 
                                 let mut msg = res_header.serialize().to_vec();
                                 msg.extend(payload);
                                 
                                 t_clone.send(&msg, Some(src)).unwrap();
                             }
                         }
                    }
                },
                Err(e) => println!("Receive error: {}", e),
            }
        }
    }, None::<i32>);
    
    // Client Logic (Wait for others to start)
    thread::sleep(Duration::from_secs(2));
    
    // 1. Call Python String Service (0x2001, 0x0001)
    let req = PyStringRequest { op: 1, text: "Hello Rust".to_string() };
    send_request(transport.clone(), 30502, 0x2001, 0x0001, req);

    // 2. Call C++ Sort Service (0x3001, 0x0001)
    let req = CppSortRequest { method: 1, data: vec![5, 1, 9, 3] };
    send_request(transport.clone(), 30503, 0x3001, 0x0001, req);
    
    // Keep alive
    loop { thread::sleep(Duration::from_secs(1)); }
}

fn send_request<T: SomeIpSerialize>(transport: Arc<UdpTransport>, port: u16, service_id: u16, method: u16, payload_obj: T) {
    let mut payload = Vec::new();
    payload_obj.serialize(&mut payload).unwrap();
    
    let header = SomeIpHeader::new(service_id, method, 0x1111, 0x0001, 0x00, payload.len() as u32);
    let mut msg = header.serialize().to_vec();
    msg.extend(payload);
    
    let dest: SocketAddr = format!("127.0.0.1:{}", port).parse().unwrap();
    transport.send(&msg, Some(dest)).unwrap();
    println!("Rust Client: Sent request to port {}", port);
    
    // Response handling omitted for sync demo logic, usually async wait.
}
