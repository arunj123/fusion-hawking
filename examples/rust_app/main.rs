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

use fusion_hawking::logging::LogLevel;

// --- Service Implementations ---
struct MathImpl {
    logger: Arc<dyn fusion_hawking::logging::FusionLogger>,
}
impl MathServiceProvider for MathImpl {
    fn add(&self, a: i32, b: i32) -> i32 {
        self.logger.log(LogLevel::Debug, "MathService", &format!("Math.Add({}, {})", a, b));
        a + b
    }
    fn sub(&self, a: i32, b: i32) -> i32 {
        self.logger.log(LogLevel::Info, "MathService", &format!("Math.Sub({}, {})", a, b));
        a - b
    }
}

fn main() {
    // 1. Initialize Runtime from Config
    let rt = SomeIpRuntime::load("examples/config.json", "rust_app_instance");
    rt.get_logger().log(LogLevel::Info, "Main", "--- High-Level Rust Runtime Demo (Configured) ---");
    
    // Setup Ctrl+C handler for graceful shutdown
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    let l = rt.get_logger();
    ctrlc::set_handler(move || {
        l.log(LogLevel::Info, "Main", "Shutting down gracefully...");
        r.store(false, Ordering::SeqCst);
    }).expect("Error setting Ctrl-C handler");
    
    // 2. Offer Services
    let math_service = MathServiceServer::new(Arc::new(MathImpl { logger: rt.get_logger() }));
    rt.offer_service("math-service", Box::new(math_service));
    
    // 3. Start Runtime Loop (Background)
    let rt_for_loop = rt.clone();
    thread::spawn(move || {
        rt_for_loop.run();
    });
    
    // 4. Client Logic
    thread::sleep(Duration::from_secs(2));
    
    rt.get_logger().log(LogLevel::Info, "Main", "Client: Waiting to discover services...");
    
    while running.load(Ordering::Relaxed) {
        // Try to get StringClient (Python) using Alias
        if let Some(client) = rt.get_client::<StringServiceClient>("string-client") {
             rt.get_logger().log(LogLevel::Info, "Main", "Client: Found StringService! Sending Request...");
             match client.reverse("Hello World".to_string()) {
                 Ok(_) => rt.get_logger().log(LogLevel::Info, "Main", "Client: Request Sent OK"),
                 Err(e) => rt.get_logger().log(LogLevel::Error, "Main", &format!("Client: Request Failed: {}", e)),
             }
        }
        
        thread::sleep(Duration::from_secs(2));
    }
    
    rt.stop();
    rt.get_logger().log(LogLevel::Info, "Main", "Shutdown complete.");
}

