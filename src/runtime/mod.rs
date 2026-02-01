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
            .expect(&format!("Instance '{}' not found in config", instance_name))
            .clone();

        // Determine bind port (use first providing service or 0)
        let mut bind_port = 0;
        if let Some(first_svc) = instance_config.providing.values().next() {
            if let Some(p) = first_svc.port {
                bind_port = p;
            }
        }
        
        logger.log(LogLevel::Info, "Runtime", &format!("Initializing '{}' on port {}", instance_name, bind_port));

        let sd_multicast: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        // Bind to multicast port with SO_REUSEADDR for port sharing
        let sd_bind: SocketAddr = "0.0.0.0:30490".parse().unwrap();
        let sd_transport = UdpTransport::new_multicast(sd_bind).expect("Failed to bind SD transport");
        // Join multicast group
        let multicast_ip: Ipv4Addr = "224.0.0.1".parse().unwrap();
        let any_interface: Ipv4Addr = "0.0.0.0".parse().unwrap();
        let _ = sd_transport.join_multicast_v4(&multicast_ip, &any_interface);
        let sd = ServiceDiscovery::new(sd_transport, sd_multicast);
        
        let bind_any = if instance_config.ip_version == 6 { "[::]" } else { "0.0.0.0" };
        let addr: SocketAddr = format!("{}:{}", bind_any, bind_port).parse().unwrap();
        let transport = UdpTransport::new(addr).expect("Failed to bind Transport");
        transport.set_nonblocking(true).unwrap();

        let rt = Arc::new(Self {
            transport: Arc::new(transport),
            sd: Arc::new(Mutex::new(sd)),
            services: Arc::new(RwLock::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(true)),
            config: Some(instance_config),
            logger,
        });
        
        rt
    }

    // Deprecated constructor for backward compatibility during migration
    pub fn new(port: u16) -> Arc<Self> {
        let logger = ConsoleLogger::new();
        logger.log(LogLevel::Warn, "Runtime", "Using deprecated constructor SomeIpRuntime::new()");
        
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
            config: None,
            logger,
        })
    }
    
    pub fn get_transport(&self) -> Arc<UdpTransport> {
        self.transport.clone()
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

        let sd = self.sd.lock().unwrap();
        if let Some(endpoint) = sd.get_service(service_id) {
             Some(T::new(self.transport.clone(), endpoint))
        } else {
             // Check config for static IP?
             if let Some(cfg) = &self.config {
                 if let Some(req_cfg) = cfg.required.get(alias) {
                     if let (Some(ip), Some(port)) = (&req_cfg.static_ip, &req_cfg.static_port) {
                          let addr_str = format!("{}:{}", ip, port);
                          if let Ok(addr) = addr_str.parse() {
                              self.logger.log(LogLevel::Info, "Runtime", &format!("Validated static config for {}", alias));
                              return Some(T::new(self.transport.clone(), addr));
                          }
                     }
                 }
             }
             
             self.logger.log(LogLevel::Debug, "Runtime", &format!("Service '{}' (0x{:04x}) not found yet.", alias, service_id));
             None
        }
    }

    pub fn offer_service(&self, alias: &str, instance: Box<dyn RequestHandler>) {
        // Resolve Config
        let (service_id, instance_id, port) = if let Some(cfg) = &self.config {
            if let Some(prov_cfg) = cfg.providing.get(alias) {
                (prov_cfg.service_id, prov_cfg.instance_id, prov_cfg.port.unwrap_or(0))
            } else {
                self.logger.log(LogLevel::Warn, "Runtime", &format!("Alias '{}' not found in config. Using struct defaults.", alias));
                (instance.service_id(), 1, self.transport.local_addr().unwrap().port())
            }
        } else {
            (instance.service_id(), 1, self.transport.local_addr().unwrap().port())
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
        
        sd.offer_service(service_id, instance_id, 1, 0, final_port, 0x11); // 0x11 = UDP
        self.logger.log(LogLevel::Info, "Runtime", &format!("Offered Service '{}' (0x{:04x}) on port {}", alias, service_id, final_port));
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
                Err(e) => self.logger.log(LogLevel::Error, "Runtime", &format!("RX Error: {}", e)),
            }
        }
    }
    
    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
    }
}
