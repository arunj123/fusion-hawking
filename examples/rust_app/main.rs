use fusion_hawking::runtime::SomeIpRuntime;
// Include generated code relative to the workspace root (assumed CWD for cargo run usually, but path relative to file is tricky with include)
// Using CARGO_MANIFEST_DIR which points to the package root (fusion-hawking dir)
pub mod generated {
    include!(concat!(env!("CARGO_MANIFEST_DIR"), "/build/generated/rust/mod.rs"));
}
use generated::{
    MathServiceProvider, MathServiceServer,
    StringServiceClient
};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

// --- Service Implementations ---
struct MathImpl;
impl MathServiceProvider for MathImpl {
    fn add(&self, a: i32, b: i32) -> i32 {
        println!("[RUST] Server: Math.Add({}, {})", a, b);
        a + b
    }
    fn sub(&self, a: i32, b: i32) -> i32 {
        println!("[RUST] Server: Math.Sub({}, {})", a, b);
        a - b
    }
}

fn main() {
    println!("[RUST] --- High-Level Rust Runtime Demo (Configured) ---");
    
    // Setup Ctrl+C handler for graceful shutdown
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    ctrlc::set_handler(move || {
        println!("[RUST] Shutting down gracefully...");
        r.store(false, Ordering::SeqCst);
    }).expect("Error setting Ctrl-C handler");
    
    // 1. Initialize Runtime from Config
    let rt = SomeIpRuntime::load("examples/config.json", "rust_app_instance");
    
    // 2. Offer Services
    let math_service = MathServiceServer::new(Arc::new(MathImpl));
    rt.offer_service("math-service", Box::new(math_service));
    
    // 3. Start Runtime Loop (Background)
    let rt_for_loop = rt.clone();
    thread::spawn(move || {
        rt_for_loop.run();
    });
    
    // 4. Client Logic
    thread::sleep(Duration::from_secs(2));
    
    println!("[RUST] Client: Waiting to discover services...");
    
    while running.load(Ordering::Relaxed) {
        // Try to get StringClient (Python) using Alias
        if let Some(client) = rt.get_client::<StringServiceClient>("string-client") {
             println!("[RUST] Client: Found StringService! Sending Request...");
             match client.reverse("Hello World".to_string()) {
                 Ok(_) => println!("[RUST] Client: Request Sent OK"),
                 Err(e) => println!("[RUST] Client: Request Failed: {}", e),
             }
        }
        
        thread::sleep(Duration::from_secs(2));
    }
    
    rt.stop();
    println!("[RUST] Shutdown complete.");
}

