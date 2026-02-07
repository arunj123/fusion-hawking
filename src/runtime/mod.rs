//! # SOME/IP Runtime Module
//!
//! High-level runtime for SOME/IP applications with service lifecycle management.
//!
//! ## Key Types
//!
//! - [`SomeIpRuntime`] - Main runtime for service providers and consumers
//! - [`RequestHandler`] - Trait for implementing service handlers
//! - [`ServiceClient`] - Trait for client proxy implementations
//! - [`ThreadPool`] - Concurrent request handling
//!
//! ## Lifecycle
//!
//! 1. Load configuration: `SomeIpRuntime::load("config.json", "my_instance")`
//! 2. Register services: `runtime.offer_service("alias", handler)`
//! 3. Start runtime: `runtime.run()`
//! 4. Stop gracefully: `runtime.stop()`
//!
//! ## Example
//!
//! ```ignore
//! let runtime = SomeIpRuntime::load("config.json", "server");
//! runtime.offer_service("math", Box::new(MathServiceServer::new(provider)));
//! runtime.run();
//! ```

pub mod threadpool;
pub mod dispatcher;
pub mod config;

pub use threadpool::*;
use config::{SystemConfig, InstanceConfig};
use std::fs::File;
use std::io::BufReader;

use std::sync::{Arc, Mutex, RwLock};
use std::net::{SocketAddr, Ipv4Addr};
use std::collections::HashMap;
use std::thread;
use std::time::Duration;
use std::sync::atomic::{AtomicBool, Ordering};
use crate::transport::{UdpTransport, SomeIpTransport};
use crate::sd::machine::ServiceDiscovery;
use crate::codec::SomeIpHeader;

pub trait RequestHandler: Send + Sync {
    fn service_id(&self) -> u16;
    fn major_version(&self) -> u8;
    fn minor_version(&self) -> u32;
    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>>;
}

pub trait ServiceClient {
    const SERVICE_ID: u16;
    fn new(transport: Arc<UdpTransport>, target: SocketAddr) -> Self;
}

use crate::logging::{FusionLogger, ConsoleLogger, LogLevel};

pub struct SomeIpRuntime {
    transport: Arc<UdpTransport>,
    sd: Arc<Mutex<ServiceDiscovery>>,
    services: Arc<RwLock<HashMap<u16, Box<dyn RequestHandler>>>>,
    running: Arc<AtomicBool>,
    config: Option<InstanceConfig>,
    pending_requests: Arc<Mutex<HashMap<(u16, u16, u16), tokio::sync::oneshot::Sender<Vec<u8>>>>>,
    session_manager: Arc<Mutex<HashMap<(u16, u16), u16>>>,
    logger: Arc<dyn FusionLogger>,
}

impl SomeIpRuntime {
    pub fn load(config_path: &str, instance_name: &str) -> Arc<Self> {
        let logger = ConsoleLogger::new();
        logger.log(LogLevel::Info, "Runtime", &format!("Loading config from {}", config_path));

        let file = File::open(config_path).expect("Failed to open config file");
        let reader = BufReader::new(file);
        let sys_config: SystemConfig = serde_json::from_reader(reader).expect("Failed to parse config json");
        
        let instance_config = sys_config.instances.get(instance_name)
            .unwrap_or_else(|| panic!("Instance '{}' not found in config", instance_name))
            .clone();

        // Determine bind port (use first providing service or 0)
        let mut bind_port = 0;
        if let Some(first_svc) = instance_config.providing.values().next() {
            if let Some(p) = first_svc.port {
                bind_port = p;
            }
        }
        
        logger.log(LogLevel::Info, "Runtime", &format!("Initializing '{}' on port {}", instance_name, bind_port));

        // Use Configured SD Settings
        let multicast_addr = &instance_config.sd.multicast_ip;
        let multicast_port = instance_config.sd.multicast_port;
        
        let sd_multicast: SocketAddr = format!("{}:{}", multicast_addr, multicast_port).parse().expect("Invalid SD Multicast Config");
        // Bind to multicast port with SO_REUSEADDR for port sharing
        let sd_bind: SocketAddr = format!("0.0.0.0:{}", multicast_port).parse().expect("Invalid SD Bind Config");
        let sd_transport = UdpTransport::new_multicast(sd_bind).expect("Failed to bind SD transport");
        // Join multicast group
        let multicast_ip: Ipv4Addr = multicast_addr.parse().expect("Invalid Multicast IP");
        let interface_ip: Ipv4Addr = instance_config.ip.parse().unwrap_or("0.0.0.0".parse().unwrap());
        let _ = sd_transport.join_multicast_v4(&multicast_ip, &interface_ip);
        // Set outgoing multicast interface to configured IP
        let _ = sd_transport.set_multicast_if_v4(&interface_ip);
        // Enable multicast loopback
        let _ = sd_transport.set_multicast_loop_v4(true);
        let sd = ServiceDiscovery::new(sd_transport, sd_multicast, interface_ip);
        
        let bind_any = if instance_config.ip_version == 6 { "[::]" } else { "0.0.0.0" };
        let addr: SocketAddr = format!("{}:{}", bind_any, bind_port).parse().unwrap();
        let transport = UdpTransport::new(addr).expect("Failed to bind Transport");
        transport.set_nonblocking(true).unwrap();

        Arc::new(Self {
            transport: Arc::new(transport),
            sd: Arc::new(Mutex::new(sd)),
            services: Arc::new(RwLock::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(true)),
            config: Some(instance_config),
            pending_requests: Arc::new(Mutex::new(HashMap::new())),
            session_manager: Arc::new(Mutex::new(HashMap::new())),
            logger,
        })
    }

    // Deprecated constructor for backward compatibility during migration
    pub fn new(port: u16) -> Arc<Self> {
        let logger = ConsoleLogger::new();
        logger.log(LogLevel::Warn, "Runtime", "Using deprecated constructor SomeIpRuntime::new()");
        
        let sd_multicast: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let sd_bind: SocketAddr = "0.0.0.0:0".parse().unwrap();
        let sd_transport = UdpTransport::new(sd_bind).expect("Failed to bind SD transport");
        let sd = ServiceDiscovery::new(sd_transport, sd_multicast, "127.0.0.1".parse().unwrap());
        
        let addr: SocketAddr = format!("0.0.0.0:{}", port).parse().unwrap();
        let transport = UdpTransport::new(addr).expect("Failed to bind Transport");
        transport.set_nonblocking(true).unwrap();

        Arc::new(Self {
            transport: Arc::new(transport),
            sd: Arc::new(Mutex::new(sd)),
            services: Arc::new(RwLock::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(true)),
            config: None,
            pending_requests: Arc::new(Mutex::new(HashMap::new())),
            session_manager: Arc::new(Mutex::new(HashMap::new())),
            logger,
        })
    }
    
    pub fn get_transport(&self) -> Arc<UdpTransport> {
        self.transport.clone()
    }

    pub fn get_logger(&self) -> Arc<dyn FusionLogger> {
        self.logger.clone()
    }
    
    pub fn get_client<T: ServiceClient>(&self, alias: &str) -> Option<T> {
        // Resolve Alias
        let service_id = if let Some(cfg) = &self.config {
            if let Some(req_cfg) = cfg.required.get(alias) {
                req_cfg.service_id
            } else {
                T::SERVICE_ID // Fallback
            }
        } else {
            T::SERVICE_ID
        };

        // Resolve timeout from config
        let timeout_ms = if let Some(cfg) = &self.config {
            cfg.sd.request_timeout_ms
        } else {
            2000 // Default fallback
        };
        let timeout = Duration::from_millis(timeout_ms);
        let poll_interval = Duration::from_millis(100);
        let start = std::time::Instant::now();

        loop {
            // Poll SD to process incoming offers
            {
                let mut sd = self.sd.lock().unwrap();
                sd.poll();
            }

            // Check if service is now available
            {
                let sd = self.sd.lock().unwrap();
                if let Some(endpoint) = sd.get_service(service_id) {
                    self.logger.log(LogLevel::Info, "Runtime", &format!("Discovered service '{}' (0x{:04x}) at {}", alias, service_id, endpoint));
                    return Some(T::new(self.transport.clone(), endpoint));
                }
            }

            if start.elapsed() >= timeout {
                self.logger.log(LogLevel::Warn, "Runtime", &format!("Timeout waiting for service '{}' (0x{:04x})", alias, service_id));
                return None;
            }

            thread::sleep(poll_interval);
        }
    }

    pub fn subscribe_eventgroup(&self, service_id: u16, instance_id: u16, eventgroup_id: u16, ttl: u32) {
        let mut sd = self.sd.lock().unwrap();
        sd.subscribe_eventgroup(service_id, instance_id, eventgroup_id, ttl, self.transport.local_addr().unwrap().port());
        self.logger.log(LogLevel::Info, "Runtime", &format!("Subscribing to Service 0x{:04x} EventGroup {}", service_id, eventgroup_id));
    }

    pub fn offer_service(&self, alias: &str, instance: Box<dyn RequestHandler>) {
        // Resolve Config
        let (service_id, major, minor, instance_id, port) = if let Some(cfg) = &self.config {
            if let Some(prov_cfg) = cfg.providing.get(alias) {
                (prov_cfg.service_id, prov_cfg.major_version, prov_cfg.minor_version, prov_cfg.instance_id, prov_cfg.port.unwrap_or(0))
            } else {
                self.logger.log(LogLevel::Warn, "Runtime", &format!("Alias '{}' not found in config. Using struct defaults.", alias));
                (instance.service_id(), instance.major_version(), instance.minor_version(), 1, self.transport.local_addr().unwrap().port())
            }
        } else {
            (instance.service_id(), instance.major_version(), instance.minor_version(), 1, self.transport.local_addr().unwrap().port())
        };
        
        // Register in Dispatch Map
        {
            let mut services = self.services.write().unwrap();
            services.insert(service_id, instance);
        }
        
        // Register in SD
        let mut sd = self.sd.lock().unwrap();
        // Use configured port if available, else bound port
        let final_port = if port != 0 { port } else { self.transport.local_addr().unwrap().port() };
        
        sd.offer_service(service_id, instance_id, major, minor, final_port, 0x11); // 0x11 = UDP
        self.logger.log(LogLevel::Info, "Runtime", &format!("Offered Service '{}' (0x{:04x}) on port {}", alias, service_id, final_port));
    }
    
    pub async fn send_request_and_wait(&self, service_id: u16, method_id: u16, payload: &[u8], target: SocketAddr) -> Option<Vec<u8>> {
        let session_id = {
            let mut mgr = self.session_manager.lock().unwrap();
            let counter = mgr.entry((service_id, method_id)).or_insert(1);
            let val = *counter;
            *counter = if val == 0xFFFF { 1 } else { val + 1 };
            val
        };

        let (tx, rx) = tokio::sync::oneshot::channel();
        {
            let mut pending = self.pending_requests.lock().unwrap();
            pending.insert((service_id, method_id, session_id), tx);
        }

        let header = SomeIpHeader::new(service_id, method_id, 0, session_id, 0x00, payload.len() as u32);
        let mut msg = header.serialize().to_vec();
        msg.extend_from_slice(payload);
        
        if let Err(_) = self.transport.send(&msg, Some(target)) {
            let mut pending = self.pending_requests.lock().unwrap();
            pending.remove(&(service_id, method_id, session_id));
            return None;
        }

        match tokio::time::timeout(Duration::from_secs(2), rx).await {
            Ok(Ok(res)) => Some(res),
            _ => {
                let mut pending = self.pending_requests.lock().unwrap();
                pending.remove(&(service_id, method_id, session_id));
                None
            }
        }
    }

    pub fn run(&self) {
        self.logger.log(LogLevel::Info, "Runtime", "Event Loop Started");
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
                         // Handle RESPONSE (0x80)
                         if header.message_type == 0x80 {
                             let mut pending = self.pending_requests.lock().unwrap();
                             if let Some(tx) = pending.remove(&(header.service_id, header.method_id, header.session_id)) {
                                 let _ = tx.send(buf[16..size].to_vec());
                             }
                             continue;
                         }

                         // Dispatch
                         let services = self.services.read().unwrap();
                         
                         // Handle Notification (0x02)
                         if header.message_type == 0x02 {
                             self.logger.log(LogLevel::Info, "Runtime", &format!("Received Notification: Service 0x{:04x} Event/Method 0x{:04x} Payload {} bytes", header.service_id, header.method_id, buf[16..size].len()));
                             continue;
                         }

                         if let Some(handler) = services.get(&header.service_id) {
                             // Only handle Requests (0x00) or Requests No Return (0x01)
                             if header.message_type == 0x00 || header.message_type == 0x01 {
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
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) => self.logger.log(LogLevel::Error, "Runtime", &format!("RX Error: {}", e)),
            }
        }
    }
    
    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
    }
}
