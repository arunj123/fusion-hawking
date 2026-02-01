use fusion_hawking::runtime::SomeIpRuntime;
use fusion_hawking::generated::{
    MathServiceProvider, MathServiceServer,
    StringServiceClient
};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

// --- Service Implementations ---
struct MathImpl;
impl MathServiceProvider for MathImpl {
    fn add(&self, a: i32, b: i32) -> i32 {
        println!("Server: Math.Add({}, {})", a, b);
        a + b
    }
    fn sub(&self, a: i32, b: i32) -> i32 {
        println!("Server: Math.Sub({}, {})", a, b);
        a - b
    }
}

fn main() -> std::io::Result<()> {
    println!("--- High-Level Rust Runtime Demo (Configured) ---");
    
    // 1. Initialize Runtime from Config
    // Assumes running from project root where examples/config.json exists
    let rt = SomeIpRuntime::load("examples/config.json", "rust_app_instance");
    
    // 2. Offer Services
    let math_service = MathServiceServer::new(Arc::new(MathImpl));
    rt.offer_service("math-service", Box::new(math_service));
    
    // 3. Start Runtime Loop (Background)
    let rt_clone = rt.clone();
    thread::spawn(move || {
        rt_clone.run();
    });
    
    // 4. Client Logic
    thread::sleep(Duration::from_secs(2));
    
    println!("Client: Waiting to discover services...");
    
    loop {
        // Try to get StringClient (Python) using Alias
        if let Some(client) = rt.get_client::<StringServiceClient>("string-client") {
             println!("Client: Found StringService! Sending Request...");
             match client.reverse("Hello World".to_string()) {
                 Ok(_) => println!("Client: Request Sent OK"),
                 Err(e) => println!("Client: Request Failed: {}", e),
             }
        }
        
        thread::sleep(Duration::from_secs(2));
    }
    Ok(())
}
