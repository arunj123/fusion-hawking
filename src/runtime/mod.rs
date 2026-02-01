pub mod threadpool;
pub mod dispatcher;

pub use threadpool::*;

use std::sync::{Arc, Mutex, RwLock};
use std::net::SocketAddr;
use std::collections::HashMap;
use std::thread;
use std::time::Duration;
use std::sync::atomic::{AtomicBool, Ordering};
use crate::transport::{UdpTransport, SomeIpTransport};
use crate::sd::machine::ServiceDiscovery;
use crate::codec::{SomeIpHeader, SomeIpDeserialize, SomeIpSerialize};

pub trait RequestHandler: Send + Sync {
    fn service_id(&self) -> u16;
    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>>;
}

pub struct SomeIpRuntime {
    transport: Arc<UdpTransport>,
    sd: Arc<Mutex<ServiceDiscovery>>,
    services: Arc<RwLock<HashMap<u16, Box<dyn RequestHandler>>>>,
    running: Arc<AtomicBool>,
}

impl SomeIpRuntime {
    pub fn new(port: u16) -> Arc<Self> {
        let sd_multicast: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let sd_bind: SocketAddr = "0.0.0.0:0".parse().unwrap();
        let sd_transport = UdpTransport::new(sd_bind).expect("Failed to bind SD transport");
        let sd = ServiceDiscovery::new(sd_transport, sd_multicast);
        
        let addr: SocketAddr = format!("0.0.0.0:{}", port).parse().unwrap();
        let transport = UdpTransport::new(addr).expect("Failed to bind Transport");
        transport.set_nonblocking(true).unwrap();

        Arc::new(Self {
            transport: Arc::new(transport),
            sd: Arc::new(Mutex::new(sd)),
            services: Arc::new(RwLock::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(true)),
        })
    }
    
    pub fn get_transport(&self) -> Arc<UdpTransport> {
        self.transport.clone()
    }

    pub fn offer_service(&self, instance: Box<dyn RequestHandler>) {
        let service_id = instance.service_id();
        
        // Register in Dispatch Map
        {
            let mut services = self.services.write().unwrap();
            services.insert(service_id, instance);
        }
        
        // Register in SD
        let port = self.transport.local_addr().unwrap().port();
        let mut sd = self.sd.lock().unwrap();
        // Assume instance ID 1 for high level abstraction
        sd.offer_service(service_id, 1, 1, 0, port, 0x11); // 0x11 = UDP
        println!("Runtime: Offered Service 0x{:04x} on port {}", service_id, port);
    }
    
    pub fn run(&self) {
        println!("Runtime: Event Loop Started");
        let mut buf = [0u8; 1500];
        
        while self.running.load(Ordering::Relaxed) {
            // 1. Poll SD
            {
                let mut sd = self.sd.lock().unwrap();
                sd.poll();
            }
            
            // 2. Poll Transport
            match self.transport.receive(&mut buf) {
                Ok((size, src)) => {
                    if size < 16 { continue; }
                     if let Ok(header) = SomeIpHeader::deserialize(&buf[..16]) {
                         // Dispatch
                         let services = self.services.read().unwrap();
                         if let Some(handler) = services.get(&header.service_id) {
                             if let Some(res_payload) = handler.handle(&header, &buf[16..size]) {
                                 // Send Response
                                  let res_header = SomeIpHeader::new(
                                     header.service_id, header.method_id, 
                                     header.client_id, header.session_id, 
                                     0x80, res_payload.len() as u32
                                 );
                                 
                                 let mut msg = res_header.serialize().to_vec();
                                 msg.extend(res_payload);
                                 let _ = self.transport.send(&msg, Some(src));
                             }
                         }
                     }
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) => println!("Runtime RX Error: {}", e),
            }
        }
    }
    
    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
    }
}
