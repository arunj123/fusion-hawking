use fusion_hawking::codec::{SomeIpHeader, SomeIpSerialize}; // Keep Serialize for Client
use fusion_hawking::transport::{UdpTransport, SomeIpTransport};
use fusion_hawking::runtime::ThreadPool;
use fusion_hawking::generated::{
    MathServiceProvider, MathServiceServer,
    StringServiceClient, SortServiceClient
};
use fusion_hawking::{ServiceDiscovery}; 
use std::net::{SocketAddr};
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use std::io::{ErrorKind};
use std::thread;
use std::time::Duration;

const MATH_PORT: u16 = 30501;

// --- 1. Implement Service Provider ---
struct MathServiceImpl;
impl MathServiceProvider for MathServiceImpl {
    fn add(&self, a: i32, b: i32) -> i32 {
        println!("MathService: add({}, {})", a, b);
        a + b
    }
    fn sub(&self, a: i32, b: i32) -> i32 {
        println!("MathService: sub({}, {})", a, b);
        a - b
    }
}

fn main() {
    println!("Starting Rust Demo App (Math Service)...");
    
    // Graceful Shutdown Flag
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    ctrlc::set_handler(move || {
        println!("\nRust Service: Ctrl+C received. Shutting down...");
        r.store(false, Ordering::SeqCst);
    })
    .expect("Error setting Ctrl-C handler");

    // 1. Start Service Discovery
    let sd_multicast: SocketAddr = "224.0.0.1:30490".parse().unwrap();
    let sd_bind: SocketAddr = "0.0.0.0:0".parse().unwrap();
    let sd_transport = UdpTransport::new(sd_bind).expect("Failed to bind SD transport");
    let mut sd = ServiceDiscovery::new(sd_transport, sd_multicast);
    
    // Offer Math Service (0x1001, Instance 1) on port MATH_PORT (UDP 0x11)
    println!("Rust Service: Offering Service 0x1001 on port {}", MATH_PORT);
    sd.offer_service(0x1001, 1, 1, 0, MATH_PORT, 0x11);
    
    // Run SD in background thread
    let sd_running = running.clone();
    thread::spawn(move || {
        while sd_running.load(Ordering::Relaxed) {
            sd.poll();
            thread::sleep(Duration::from_millis(10));
        }
        println!("Rust Service: SD thread stopped.");
    });

    let pool = ThreadPool::new(4);
    
    // 2. Start Service Transport
    let addr: SocketAddr = format!("127.0.0.1:{}", MATH_PORT).parse().unwrap();
    let transport = Arc::new(UdpTransport::new(addr).expect("Failed to bind Service transport"));
    transport.set_nonblocking(true).expect("Failed to set non-blocking");
    
    let t_clone = transport.clone();
    
    // Initialize Server Stub
    let impl_service = Arc::new(MathServiceImpl);
    let server = MathServiceServer::new(impl_service);
    let server = Arc::new(server); // Shared for threads if needed

    // Server Loop
    let server_running = running.clone();
    pool.execute(move || {
        let mut buf = [0u8; 1500];
        while server_running.load(Ordering::Relaxed) {
            match t_clone.receive(&mut buf) {
                Ok((size, src)) => {
                    if size < 16 { continue; }
                    
                    // Peek Header
                     if let Ok(header) = SomeIpHeader::deserialize(&buf[..16]) {
                         // Use Generated Binder to handle request
                         if let Some(res_payload) = server.handle_request(&header, &buf[16..size]) {
                             // Construct Response Header
                             let res_header = SomeIpHeader::new(
                                 header.service_id, header.method_id, 
                                 header.client_id, header.session_id, 
                                 0x80, res_payload.len() as u32
                             );
                             
                             let mut msg = res_header.serialize().to_vec();
                             msg.extend(res_payload);
                             
                             let _ = t_clone.send(&msg, Some(src));
                         }
                     }
                },
                Err(ref e) if e.kind() == ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(10));
                }
                Err(e) => println!("Receive error: {}", e),
            }
        }
    }, None::<i32>);
    
    // Client Logic (Wait for others to start)
    thread::sleep(Duration::from_secs(2));
    
    // Use Generated Clients
    // 1. Python String Service (0x2001)
    let py_addr: SocketAddr = "127.0.0.1:30502".parse().unwrap();
    let py_client = StringServiceClient::new(transport.clone(), py_addr);
    
    println!("Rust Client: Calling StringService.reverse('Hello Rust')...");
    let _ = py_client.reverse("Hello Rust".to_string());

    // 2. C++ Sort Service (0x3001)
    let cpp_addr: SocketAddr = "127.0.0.1:30503".parse().unwrap();
    let cpp_client = SortServiceClient::new(transport.clone(), cpp_addr);
    
    println!("Rust Client: Calling SortService.sort_asc([5, 1, 9, 3])...");
    let _ = cpp_client.sort_asc(vec![5, 1, 9, 3]);
    
    // Keep alive
    loop { thread::sleep(Duration::from_secs(1)); }
}

