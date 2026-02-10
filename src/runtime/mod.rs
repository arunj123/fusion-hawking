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
use std::net::{SocketAddr, Ipv4Addr, Ipv6Addr, IpAddr};
use std::collections::HashMap;
use std::thread;
use std::time::Duration;
use std::sync::atomic::{AtomicBool, Ordering};
use crate::transport::{UdpTransport, SomeIpTransport};
use crate::sd::machine::{ServiceDiscovery, DEFAULT_SD_PORT};
use crate::codec::SomeIpHeader;

pub trait RequestHandler: Send + Sync {
    fn service_id(&self) -> u16;
    fn major_version(&self) -> u8;
    fn minor_version(&self) -> u32;
    fn handle(&self, header: &SomeIpHeader, payload: &[u8]) -> Option<Vec<u8>>;
}

pub trait ServiceClient {
    const SERVICE_ID: u16;
    fn new(transport: Arc<dyn SomeIpTransport>, target: SocketAddr) -> Self;
}

use crate::logging::{FusionLogger, ConsoleLogger, LogLevel};

pub struct SomeIpRuntime {
    udp_transports: Vec<Arc<dyn SomeIpTransport>>,
    tcp_transports: Vec<Arc<dyn SomeIpTransport>>,
    sd: Arc<Mutex<ServiceDiscovery>>,
    services: Arc<RwLock<HashMap<u16, Box<dyn RequestHandler>>>>,
    running: Arc<AtomicBool>,
    config: Option<InstanceConfig>,
    endpoints: HashMap<String, config::EndpointConfig>,
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

        let endpoints = sys_config.endpoints.clone();

        // Initialize Transports based on configured endpoints (providing + required)
        let mut udp_transports: Vec<Arc<dyn SomeIpTransport>> = Vec::new();
        let mut tcp_transports: Vec<Arc<dyn SomeIpTransport>> = Vec::new();
        let mut bound_endpoints: HashMap<(String, u16, String), Arc<dyn SomeIpTransport>> = HashMap::new();

        let mut all_endpoint_names = Vec::new();
        if let Some(ref ep) = instance_config.endpoint {
            all_endpoint_names.push(ep.clone());
        }
        for svc in instance_config.providing.values() {
            all_endpoint_names.push(svc.endpoint.clone());
        }
        for client in instance_config.required.values() {
            if let Some(ref ep) = client.endpoint {
                all_endpoint_names.push(ep.clone());
            }
        }

        for endpoint_name in all_endpoint_names {
            let endpoint = endpoints.get(&endpoint_name)
                .expect(&format!("Endpoint {} not found", endpoint_name));
            
            let port = endpoint.port;
            let protocol = endpoint.protocol.to_lowercase();
            
            if endpoint.interface.is_none() || endpoint.interface.as_ref().unwrap().is_empty() {
                panic!("Mandatory configuration 'interface' missing for endpoint '{}'", endpoint_name);
            }
            
            let key = (endpoint.ip.clone(), port, protocol.clone());
            if !bound_endpoints.contains_key(&key) {
                if protocol == "tcp" {
                    // TCP Connect is different, we usually bind servers for providing.
                    // For client-only TCP, we don't 'bind' here, it connects on demand.
                    // But for UDP we always bind to receive.
                    continue; 
                }

                let addr: SocketAddr = if endpoint.version == 6 {
                    format!("[{}]:{}", endpoint.ip, port).parse().expect("Invalid IPv6")
                } else {
                    format!("{}:{}", endpoint.ip, port).parse().expect("Invalid IPv4")
                };

                let bind_addr: SocketAddr = if endpoint.version == 6 {
                    SocketAddr::new(IpAddr::V6(Ipv6Addr::UNSPECIFIED), addr.port())
                } else {
                    SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), addr.port())
                };

                let transport: Arc<dyn SomeIpTransport> = Arc::new(UdpTransport::new(bind_addr).expect("Failed to bind UDP Transport"));
                transport.set_nonblocking(true).unwrap();
                
                bound_endpoints.insert(key, transport.clone());
                udp_transports.push(transport);
                logger.log(LogLevel::Info, "Runtime", &format!("Bound {} transport on {}", protocol, addr));
            }
        }
        
        // Handle TCP Providing if any
        for svc in instance_config.providing.values() {
            let endpoint = endpoints.get(&svc.endpoint).unwrap();
            let protocol = endpoint.protocol.to_lowercase();
            if protocol == "tcp" {
                let addr: SocketAddr = if endpoint.version == 6 {
                    format!("[{}]:{}", endpoint.ip, endpoint.port).parse().expect("Invalid IPv6")
                } else {
                    format!("{}:{}", endpoint.ip, endpoint.port).parse().expect("Invalid IPv4")
                };
                let key = (endpoint.ip.clone(), endpoint.port, protocol);
                if !bound_endpoints.contains_key(&key) {
                    let server = crate::transport::TcpServer::bind(addr).expect("Failed to bind TCP Server");
                    let transport = Arc::new(crate::transport::TcpServerTransport::new(server));
                    transport.set_nonblocking(true).unwrap();
                    bound_endpoints.insert(key, transport.clone());
                    tcp_transports.push(transport);
                    logger.log(LogLevel::Info, "Runtime", &format!("Bound tcp server on {}", addr));
                }
            }
        }
        
        // All transports must be explicitly configured according to Project Rules.

        // Initialize SD
        let sd_v4_endpoint = instance_config.sd.multicast_endpoint.as_ref()
            .and_then(|name| endpoints.get(name));
        
        let sd_v6_endpoint = instance_config.sd.multicast_endpoint_v6.as_ref()
            .and_then(|name| endpoints.get(name));

        let sd_v4_ip = sd_v4_endpoint.map(|e| e.ip.clone()).expect("SD Multicast IPv4 endpoint config missing");
        let sd_v4_port = sd_v4_endpoint.map(|e| e.port).unwrap_or(DEFAULT_SD_PORT);

        let sd_v6_ip = sd_v6_endpoint.map(|e| e.ip.clone()).expect("SD Multicast IPv6 endpoint config missing");
        let sd_v6_port = sd_v6_endpoint.map(|e| e.port).unwrap_or(DEFAULT_SD_PORT);

        // SD Interface Validation
        if let Some(ep) = sd_v4_endpoint {
            if ep.interface.is_none() || ep.interface.as_ref().unwrap().is_empty() {
                 logger.log(LogLevel::Error, "Runtime", "Mandatory configuration 'interface' missing for SD Endpoint (v4).");
            }
        }
        if let Some(ep) = sd_v6_endpoint {
             if ep.interface.is_none() || ep.interface.as_ref().unwrap().is_empty() {
                 logger.log(LogLevel::Error, "Runtime", "Mandatory configuration 'interface' missing for SD Endpoint (v6).");
             }
        }

        // Finding interface IP for V4 (heuristically use first provided service's endpoint if V4)
        let interface_ip_v4: Option<Ipv4Addr> = instance_config.providing.values()
            .find_map(|svc| {
                let ep = endpoints.get(&svc.endpoint)?;
                if ep.version == 4 { ep.ip.parse().ok() } else { None }
            })
            .or_else(|| {
                // Fallback: check required services
                instance_config.required.values().find_map(|svc| {
                     let ep = endpoints.get(svc.endpoint.as_ref()?)?;
                     if ep.version == 4 { ep.ip.parse().ok() } else { None }
                })
            });

        let sd_transport_v4 = if interface_ip_v4.is_some() {
            let sd_bind_v4: SocketAddr = SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), sd_v4_port);
            UdpTransport::new_multicast(sd_bind_v4).ok()
        } else {
            logger.log(LogLevel::Warn, "Runtime", "Interface IP (v4) is not configured. SD v4 will be disabled.");
            None
        };
        
        // IPv6 SD - similar fallback, but optional
        let interface_ip_v6: Option<Ipv6Addr> = instance_config.providing.values()
            .find_map(|svc| {
                let ep = endpoints.get(&svc.endpoint)?;
                if ep.version == 6 { ep.ip.parse().ok() } else { None }
            })
            .or_else(|| {
                // Fallback: check required services
                instance_config.required.values().find_map(|svc| {
                     let ep = endpoints.get(svc.endpoint.as_ref()?)?;
                     if ep.version == 6 { ep.ip.parse().ok() } else { None }
                })
            });

        let sd_transport_v6 = if interface_ip_v6.is_some() {
            let sd_bind_v6: SocketAddr = SocketAddr::new(IpAddr::V6(Ipv6Addr::UNSPECIFIED), sd_v6_port);
            UdpTransport::new_multicast(sd_bind_v6).ok()
        } else {
            logger.log(LogLevel::Warn, "Runtime", "Interface IP (v6) is not configured. SD v6 will be disabled.");
            None
        };

        let multicast_ip_v4_opt: Option<Ipv4Addr> = sd_v4_ip.parse().ok();
        let multicast_ip_v6_opt: Option<Ipv6Addr> = sd_v6_ip.parse().ok();

        let hops = instance_config.sd.multicast_hops as u32;
        
        // Resolve interface index dynamically for IPv6
        let iface_idx = {
            let iface_name = sd_v6_endpoint.and_then(|e| e.interface.as_ref())
                .or_else(|| sd_v4_endpoint.and_then(|e| e.interface.as_ref()))
                .map(|s| s.to_owned())
                .unwrap_or_default();
            
            if iface_name.to_lowercase().contains("lo") || iface_name.to_lowercase().contains("loopback") {
                if cfg!(target_os = "windows") { 1 } else { 0 }
            } else if cfg!(target_os = "windows") {
                use std::process::Command;
                let mut found_idx = 0;
                if let Ok(out) = Command::new("netsh").args(&["interface", "ipv4", "show", "interfaces"]).output() {
                    let stdout = String::from_utf8_lossy(&out.stdout);
                    for line in stdout.lines() {
                        if line.to_lowercase().contains(&iface_name.to_lowercase()) {
                            if let Some(idx_str) = line.split_whitespace().next() {
                                if let Ok(idx) = idx_str.parse::<u32>() {
                                    found_idx = idx;
                                    break;
                                }
                            }
                        }
                    }
                }
                found_idx
            } else {
                0 // Default
            }
        };

        if let Some(ref t4) = sd_transport_v4 {
            let _ = t4.set_multicast_ttl_v4(hops);
            let _ = t4.set_multicast_loop_v4(true);
            if let (Some(mcast_v4), Some(ip_v4)) = (multicast_ip_v4_opt, interface_ip_v4) {
                 let _ = t4.join_multicast_v4(&mcast_v4, &ip_v4);
                 let _ = t4.set_multicast_if_v4(&ip_v4);
            }
        }
        
        if let Some(ref t6) = sd_transport_v6 {
            if let Some(mcast_v6) = multicast_ip_v6_opt {
                let _ = t6.join_multicast_v6(&mcast_v6, iface_idx);
                let _ = t6.set_multicast_if_v6(iface_idx);
                let _ = t6.set_multicast_hops_v6(hops);
            }
        }

        let multicast_group_v4: Option<SocketAddr> = multicast_ip_v4_opt.map(|ip| (ip, sd_v4_port).into());
        let multicast_group_v6: Option<SocketAddr> = multicast_ip_v6_opt.map(|ip| (ip, sd_v6_port).into());

        let sd = ServiceDiscovery::new(sd_transport_v4, sd_transport_v6, interface_ip_v4, interface_ip_v6,
                                       multicast_group_v4, multicast_group_v6);

        Arc::new(Self {
            udp_transports,
            tcp_transports,
            sd: Arc::new(Mutex::new(sd)),
            services: Arc::new(RwLock::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(true)),
            config: Some(instance_config),
            endpoints,
            pending_requests: Arc::new(Mutex::new(HashMap::new())),
            session_manager: Arc::new(Mutex::new(HashMap::new())),
            logger,
        })
    }

    
    pub fn get_transport_v4(&self) -> Option<Arc<dyn SomeIpTransport>> {
        self.udp_transports.iter().find(|t| t.local_addr().map(|a| a.is_ipv4()).unwrap_or(false))
            .cloned()
    }

    pub fn get_transport_v6(&self) -> Option<Arc<dyn SomeIpTransport>> {
        self.udp_transports.iter().find(|t| t.local_addr().map(|a| a.is_ipv6()).unwrap_or(false))
            .cloned()
    }

    pub fn get_logger(&self) -> Arc<dyn FusionLogger> {
        self.logger.clone()
    }
    
    pub fn get_client<T: ServiceClient>(&self, alias: &str) -> Option<T> {
        // Resolve Alias
        let (service_id, instance_id) = if let Some(cfg) = &self.config {
            if let Some(req_cfg) = cfg.required.get(alias) {
                (req_cfg.service_id, req_cfg.instance_id)
            } else {
                (T::SERVICE_ID, 0xFFFF) // Fallback
            }
        } else {
            (T::SERVICE_ID, 0xFFFF)
        };

        let timeout_ms = if let Some(cfg) = &self.config {
            cfg.sd.request_timeout_ms
        } else {
            2000
        };
        let timeout = Duration::from_millis(timeout_ms);
        let start = std::time::Instant::now();

        loop {
            {
                let mut sd = self.sd.lock().unwrap();
                sd.poll();
            }

            {
                let sd = self.sd.lock().unwrap();
                if let Some((endpoint, proto)) = sd.get_service(service_id, instance_id) {
                    self.logger.log(LogLevel::Info, "Runtime", &format!("Discovered service '{}' (0x{:04x}) at {} (proto 0x{:02x})", alias, service_id, endpoint, proto));
                    
                    let transport: Arc<dyn SomeIpTransport> = if proto == 0x06 {
                        // TCP
                        match crate::transport::TcpTransport::connect(endpoint) {
                            Ok(t) => {
                                t.set_nonblocking(true).unwrap();
                                Arc::new(t)
                            }
                            Err(e) => {
                                self.logger.log(LogLevel::Error, "Runtime", &format!("Failed to connect to TCP service: {}", e));
                                return None;
                            }
                        }
                    } else {
                        // UDP (or default)
                        if endpoint.is_ipv4() {
                            self.udp_transports.iter().find(|t| t.local_addr().map(|a| a.is_ipv4()).unwrap_or(false))
                                .cloned()
                                .expect("No local UDP v4 transport available")
                        } else {
                            if let Some(t) = self.udp_transports.iter().find(|t| t.local_addr().map(|a| a.is_ipv6()).unwrap_or(false)) {
                                t.clone()
                            } else {
                                self.logger.log(LogLevel::Error, "Runtime", "No local UDP v6 transport available for discovered v6 service");
                                return None;
                            }
                        }
                    };
                    
                    return Some(T::new(transport, endpoint));
                }
            }

            if start.elapsed() >= timeout {
                self.logger.log(LogLevel::Warn, "Runtime", &format!("Timeout waiting for service '{}' (0x{:04x})", alias, service_id));
                return None;
            }

            thread::sleep(Duration::from_millis(100));
        }
    }


    pub fn subscribe_eventgroup(&self, service_id: u16, instance_id: u16, eventgroup_id: u16, ttl: u32) {
        let mut sd = self.sd.lock().unwrap();
        let port_v4 = self.get_transport_v4().and_then(|t| t.local_addr().ok()).map(|a| a.port()).unwrap_or(0);
        let port_v6 = self.get_transport_v6().and_then(|t| t.local_addr().ok()).map(|a| a.port()).unwrap_or(0);
        sd.subscribe_eventgroup(service_id, instance_id, eventgroup_id, ttl, port_v4, port_v6);
        self.logger.log(LogLevel::Info, "Runtime", &format!("Subscribing to Service 0x{:04x} EventGroup {} (v4: {}, v6: {})", service_id, eventgroup_id, port_v4, port_v6));
    }

    pub fn offer_service(&self, alias: &str, instance: Box<dyn RequestHandler>) {
        // Resolve Config
        let (service_id, major, minor, instance_id, endpoint_name, multicast_name) = if let Some(cfg) = &self.config {
            if let Some(prov_cfg) = cfg.providing.get(alias) {
                (prov_cfg.service_id, prov_cfg.major_version, prov_cfg.minor_version, prov_cfg.instance_id, prov_cfg.endpoint.clone(), prov_cfg.multicast.clone())
            } else {
                panic!("Alias '{}' not found in config", alias);
            }
        } else {
            panic!("offer_service requires a loaded config");
        };
        
        // Register in Dispatch Map
        {
            let mut services = self.services.write().unwrap();
            services.insert(service_id, instance);
        }
        
        let endpoint = self.endpoints.get(&endpoint_name).expect("Endpoint not found");
        let mut final_port = endpoint.port;
        if final_port == 0 {
            // Use the port from the first available UDP transport as baseline for service
            final_port = self.udp_transports.first()
                .and_then(|t| t.local_addr().ok())
                .map(|a| a.port())
                .unwrap_or(0);
        }
        
        // Register in SD
        let mut sd = self.sd.lock().unwrap();
        let protocol = endpoint.protocol.to_lowercase();
        let proto_id = if protocol == "tcp" { 0x06 } else { 0x11 };
        
        // Resolve Multicast
        let multicast = if let Some(mcast_name) = multicast_name.as_ref() {
            if let Some(m_ep) = self.endpoints.get(mcast_name) {
                let m_ip: std::net::IpAddr = m_ep.ip.parse().expect("Invalid multicast IP");
                Some((m_ip, m_ep.port))
            } else { None }
        } else { None };

        sd.offer_service(service_id, instance_id, major, minor, final_port, proto_id, multicast);
        self.logger.log(LogLevel::Info, "Runtime", &format!("Offered Service '{}' (0x{:04x}) on endpoint {} ({}:{}, {})", 
            alias, service_id, endpoint_name, endpoint.ip, final_port, protocol));
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
        
        let transport = if target.is_ipv6() { self.get_transport_v6() } else { self.get_transport_v4() };
        let transport = transport.expect("Required transport (UDP) not found for target family");
        if let Err(_) = transport.send(&msg, Some(target)) {
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
        let mut buf = [0u8; 4096];
        
        while self.running.load(Ordering::Relaxed) {
            // 1. Poll SD
            {
                let mut sd = self.sd.lock().unwrap();
                sd.poll();
            }
            
            // 2. Poll All Transports
            let mut all_transports: Vec<Arc<dyn SomeIpTransport>> = Vec::new();
            all_transports.extend(self.udp_transports.iter().cloned());
            all_transports.extend(self.tcp_transports.iter().cloned());
            
            for transport in all_transports {
                match transport.receive(&mut buf) {
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
                                 if header.message_type == 0x00 || header.message_type == 0x01 {
                                     if let Some(res_payload) = handler.handle(&header, &buf[16..size]) {
                                          let res_header = SomeIpHeader::new(
                                              header.service_id,
                                              header.method_id,
                                              header.client_id,
                                              header.session_id,
                                              0x80, // RESPONSE
                                              res_payload.len() as u32
                                          );
                                          let mut res_msg = res_header.serialize().to_vec();
                                          res_msg.extend(res_payload);
                                          let _ = transport.send(&res_msg, Some(src));
                                     }
                                 }
                             }
                         }
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(e) => {
                        self.logger.log(LogLevel::Error, "Runtime", &format!("Receive error: {}", e));
                    }
                }
            }
            
            thread::sleep(Duration::from_millis(10));
        }
    }
    
    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
    }
}
