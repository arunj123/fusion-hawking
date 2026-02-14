use fusion_hawking::runtime::SomeIpRuntime;
pub mod generated {
    include!(concat!(env!("CARGO_MANIFEST_DIR"), "/../../../build/generated/rust/mod.rs"));
}
use generated::{
    MathServiceProvider, MathServiceServer,
    ComplexTypeServiceProvider, ComplexTypeServiceServer,
    MathServiceClient, StringServiceClient, SortServiceClient, DiagnosticServiceClient,
    DeviceInfo, SystemStatus
};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

use fusion_hawking::logging::LogLevel;

// --- Math Service Implementation ---
struct MathImpl {
    logger: Arc<dyn fusion_hawking::logging::FusionLogger>,
}
impl MathServiceProvider for MathImpl {
    fn add(&self, a: i32, b: i32) -> i32 {
        self.logger.log(LogLevel::Info, "MathService", &format!("Math.Add({}, {})", a, b));
        a + b
    }
    fn sub(&self, a: i32, b: i32) -> i32 {
        self.logger.log(LogLevel::Info, "MathService", &format!("Math.Sub({}, {})", a, b));
        a - b
    }
}

// --- Complex Type Service Implementation ---
struct ComplexImpl {
    logger: Arc<dyn fusion_hawking::logging::FusionLogger>,
}
impl ComplexTypeServiceProvider for ComplexImpl {
    fn check_health(&self) -> bool {
        self.logger.log(LogLevel::Info, "ComplexService", "Health Checked: OK");
        true
    }
    fn set_threshold(&self, value: f32) {
        self.logger.log(LogLevel::Info, "ComplexService", &format!("Threshold set to {}", value));
    }
    fn update_system_status(&self, status: SystemStatus) -> bool {
        self.logger.log(LogLevel::Info, "ComplexService", &format!("System Status updated: uptime={}, devices={}", status.uptime, status.devices.len()));
        true
    }
    fn get_devices(&self) -> Vec<DeviceInfo> {
        vec![
            DeviceInfo { id: 1, name: "Sensor_A".to_string(), is_active: true, firmware_version: "1.0.1".to_string() },
            DeviceInfo { id: 2, name: "Actuator_B".to_string(), is_active: false, firmware_version: "0.9.5".to_string() },
        ]
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let config_path = if args.len() > 1 {
        &args[1]
    } else {
        "../config.json"
    };

    println!("Loading config from: {}", config_path);
    let rt = SomeIpRuntime::load(config_path, "rust_app_instance");
    let logger = rt.get_logger();
    logger.log(LogLevel::Info, "Main", &format!("--- Rust Runtime Expanded Demo (Config: {}) ---", config_path));
    
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    let l = logger.clone();
    ctrlc::set_handler(move || {
        l.log(LogLevel::Info, "Main", "Shutting down...");
        r.store(false, Ordering::SeqCst);
    }).ok();
    
    // Offer Services
    let math = MathServiceServer::new(Arc::new(MathImpl { logger: logger.clone() }));
    rt.offer_service("math-service", Box::new(math));
    
    let complex = ComplexTypeServiceServer::new(Arc::new(ComplexImpl { logger: logger.clone() }));
    rt.offer_service("complex-service", Box::new(complex));
    
    let rt_clone = rt.clone();
    thread::spawn(move || rt_clone.run());
    
    thread::sleep(Duration::from_secs(2));
    
    // Client Work
    // Wait for the service to be available before subscribing to avoid race conditions
    let mut sort_client_ready = false;
    let start_wait = std::time::Instant::now();
    logger.log(LogLevel::Info, "Main", "Waiting for sort-client to be available...");
    
    while !sort_client_ready {
        if rt.get_client::<SortServiceClient>("sort-client").is_some() {
            sort_client_ready = true;
            logger.log(LogLevel::Info, "Main", "sort-client is ready!");
        } else {
            if start_wait.elapsed() > Duration::from_secs(30) {
                logger.log(LogLevel::Error, "Main", "Timeout waiting for sort-client. Continuing anyway...");
                break;
            }
            thread::sleep(Duration::from_millis(500));
        }
    }

    // Subscribe using constants
    rt.subscribe_eventgroup(SortServiceClient::SERVICE_ID, 1, 1, 100, "primary");

    while running.load(Ordering::Relaxed) {
        if let Some(c) = rt.get_client::<MathServiceClient>("math-client-v2") {
             let _ = c.add(10, 20);
        }
        
        if let Some(c) = rt.get_client::<MathServiceClient>("math-client-v1-inst2") {
             let _ = c.add(100, 200);
        }

        if let Some(c) = rt.get_client::<StringServiceClient>("string-client") {
             let _ = c.reverse("Rust App".to_string());
        }

        if let Some(c) = rt.get_client::<SortServiceClient>("sort-client") {
             let _ = c.sort_asc(vec![9, 8, 7]);
        }
        
        if let Some(c) = rt.get_client::<DiagnosticServiceClient>("diag-client") {
             let _ = c.get_version();
        }

        thread::sleep(Duration::from_secs(2));
    }
    
    rt.stop();
}
