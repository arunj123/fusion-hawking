use fusion_hawking::runtime::{SomeIpRuntime, RequestHandler};
use fusion_hawking::codec::SomeIpHeader;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use std::sync::atomic::{AtomicBool, Ordering};

const SERVICE_ID: u16 = 0x5000;
const METHOD_ID_GET: u16 = 0x0001;
const METHOD_ID_ECHO: u16 = 0x0002;
const LARGE_PAYLOAD_SIZE: usize = 5000;

struct LargePayloadService;

impl RequestHandler for LargePayloadService {
    fn service_id(&self) -> u16 {
        SERVICE_ID
    }
    
    fn major_version(&self) -> u8 { 1 }
    fn minor_version(&self) -> u32 { 0 }

    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>> {
        let mid = header.method_id;
        
        if mid == METHOD_ID_GET {
            println!("Received GET Request for {} bytes", LARGE_PAYLOAD_SIZE);
            let mut data = Vec::with_capacity(LARGE_PAYLOAD_SIZE);
            for i in 0..LARGE_PAYLOAD_SIZE {
                data.push((i % 256) as u8);
            }
            return Some(data);
        } else if mid == METHOD_ID_ECHO {
            println!("Received ECHO Request, size={}", payload.len());
            if payload.len() != LARGE_PAYLOAD_SIZE {
                println!("WARNING: Received size {} != Expected {}", payload.len(), LARGE_PAYLOAD_SIZE);
            }
            return Some(payload.to_vec());
        }
        
        None
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let config_path = if args.len() > 1 { &args[1] } else { "examples/large_payload_test/config_rust.json" };
    
    println!("Starting Rust TP Server with config: {}", config_path);
    
    let runtime = SomeIpRuntime::load(config_path, "tp_server");
    
    runtime.offer_service("tp_service", Box::new(LargePayloadService));
    
    runtime.run();
}
