use fusion_hawking::runtime::{SomeIpRuntime, ServiceClient};
use fusion_hawking::transport::SomeIpTransport;
use std::net::SocketAddr;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

#[derive(Clone)]
struct GenericClient {
    #[allow(dead_code)]
    transport: Arc<dyn SomeIpTransport>,
    target: SocketAddr,
}

// ServiceClient usually requires Send + Sync if it's stored in the runtime or used across threads
impl ServiceClient for GenericClient {
    const SERVICE_ID: u16 = 0x1234;
    fn new(transport: Arc<dyn SomeIpTransport>, target: SocketAddr) -> Self {
        Self { transport, target }
    }
}

// Explicitly implement Send and Sync if compiler is unsure, 
// though Arc<dyn SomeIpTransport> should already be Send+Sync if the trait is.
unsafe impl Send for GenericClient {}
unsafe impl Sync for GenericClient {}

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let default_path = "client_config.json".to_string();
    let config_path = if args.len() > 1 { &args[1] } else { &default_path };
    let instance_name = "rust_client";

    println!("[Fusion Rust Client] Initializing with config: {}", config_path);
    let runtime = SomeIpRuntime::load(config_path, instance_name);
    
    let rt_clone = runtime.clone();
    thread::spawn(move || {
        rt_clone.run();
    });

    println!("[Fusion Rust Client] Searching for Service 0x1234...");
    thread::sleep(Duration::from_secs(1));

    if let Some(client) = runtime.get_client::<GenericClient>("someipy_svc") {
        println!("[Fusion Rust Client] Discovered service at {}", client.target);
        
        let msg = "Hello from Fusion Rust!";
        let payload = msg.as_bytes().to_vec();
        
        println!("[Fusion Rust Client] Sending Echo: '{}'", msg);
        match runtime.send_request_and_wait(0x1234, 0x0001, &payload, client.target).await {
            Some(response) => {
                let res_str = String::from_utf8_lossy(&response);
                println!("[Fusion Rust Client] Got Response: '{}'", res_str);
            }
            None => {
                println!("[Fusion Rust Client] RPC Error: No response received");
            }
        }
    } else {
        println!("[Fusion Rust Client] Service not found.");
    }

    runtime.stop();
    thread::sleep(Duration::from_millis(500));
}
