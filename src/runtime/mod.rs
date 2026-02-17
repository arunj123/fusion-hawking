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
use crate::sd::machine::{ServiceDiscovery, SdListener};
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
    /// Maps endpoint names to their actual bound ports (resolves ephemeral port 0)
    bound_ports: HashMap<String, u16>,
    pending_requests: Arc<Mutex<HashMap<(u16, u16, u16), tokio::sync::oneshot::Sender<Vec<u8>>>>>,
    session_manager: Arc<Mutex<HashMap<(u16, u16), u16>>>,
    tp_reassembler: Arc<Mutex<crate::codec::tp::TpReassembler>>,
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

        let mut udp_transports: Vec<Arc<dyn SomeIpTransport>> = Vec::new();
        let mut tcp_transports: Vec<Arc<dyn SomeIpTransport>> = Vec::new();
        let mut bound_endpoints: HashMap<(String, u16, String), Arc<dyn SomeIpTransport>> = HashMap::new();
        let mut bound_ports: HashMap<String, u16> = HashMap::new();

        // 1. Identify all interfaces used by this instance
        let mut iface_aliases = Vec::new();
        // Add interfaces from unicast_bind
        for iface in instance_config.unicast_bind.keys() {
            if !iface_aliases.contains(iface) { iface_aliases.push(iface.clone()); }
        }
        // Add interfaces from providing.offer_on
        for svc in instance_config.providing.values() {
            for iface in svc.offer_on.keys() {
                if !iface_aliases.contains(iface) { iface_aliases.push(iface.clone()); }
            }
        }
        // Add interfaces from required.find_on
        for req in instance_config.required.values() {
             for iface in &req.find_on {
                 if !iface_aliases.contains(iface) { iface_aliases.push(iface.clone()); }
             }
        }
        // Legacy support
        if iface_aliases.is_empty() {
             for iface in &instance_config.interfaces {
                 if !iface_aliases.contains(iface) { iface_aliases.push(iface.clone()); }
             }
        }

        if iface_aliases.is_empty() && !sys_config.interfaces.is_empty() {
             // Fallback pattern
             if sys_config.interfaces.contains_key("primary") {
                 iface_aliases.push("primary".to_string());
             } else {
                 if let Some(first) = sys_config.interfaces.keys().next() {
                     iface_aliases.push(first.clone());
                 }
             }
        }

        let mut all_discovered_endpoints = sys_config.endpoints.clone();
        
        // 2. Identify all Endpoints to Bind
        // We must bind:
        // - All unicast_bind endpoints (Control)
        // - All offer_on endpoints (Data)
        let mut endpoints_to_bind = Vec::new();
        
        // From unicast_bind
        for ep_name in instance_config.unicast_bind.values() {
            endpoints_to_bind.push(ep_name.clone());
        }
        // From offer_on
        for svc in instance_config.providing.values() {
            for ep_name in svc.offer_on.values() {
                endpoints_to_bind.push(ep_name.clone());
            }
        }
        // Legacy Config fallback (if used)
        if let Some(ep) = &instance_config.endpoint {
            endpoints_to_bind.push(ep.clone());
        }

        for alias in &iface_aliases {
            let iface_cfg = sys_config.interfaces.get(alias)
                .unwrap_or_else(|| panic!("Interface alias '{}' not found", alias));
            
            // Merge interface-specific endpoints
            for (name, ep) in &iface_cfg.endpoints {
                all_discovered_endpoints.insert(name.clone(), ep.clone());
            }
        }

        // Bind gathered endpoints
        for ep_name in endpoints_to_bind {
            if let Some(ep) = all_discovered_endpoints.get(&ep_name) {
                let ip = ep.ip.clone();
                let port = ep.port;
                let proto = ep.protocol.to_lowercase();
                
                // Heuristic: only bind local unicast IPs
                if let Ok(addr) = ip.parse::<std::net::IpAddr>() {
                    if addr.is_multicast() { continue; }
                }

                let key = (ip.clone(), port, proto.clone());
                if !bound_endpoints.contains_key(&key) {
                    let addr_str = if ep.version == 6 { format!("[{}]:{}", ip, port) } else { format!("{}:{}", ip, port) };
                    let addr: SocketAddr = addr_str.parse().expect("Invalid address");

                    if proto == "tcp" {
                        if let Ok(server) = crate::transport::TcpServer::bind(addr) {
                            let transport = Arc::new(crate::transport::TcpServerTransport::new(server));
                            transport.set_nonblocking(true).unwrap();
                            let actual_addr = transport.local_addr().unwrap_or(addr);
                            bound_ports.insert(ep_name.clone(), actual_addr.port());
                            bound_endpoints.insert((ip, actual_addr.port(), proto.clone()), transport.clone());
                            tcp_transports.push(transport);
                            logger.log(LogLevel::Info, "Runtime", &format!("Bound tcp server on {}", actual_addr));
                        }
                    } else {
                        if let Ok(transport) = UdpTransport::new(addr) {
                            let transport_arc: Arc<dyn SomeIpTransport> = Arc::new(transport);
                            transport_arc.set_nonblocking(true).unwrap();
                            let actual_addr = transport_arc.local_addr().unwrap();
                            bound_ports.insert(ep_name.clone(), actual_addr.port());
                            bound_endpoints.insert((ip, actual_addr.port(), proto.clone()), transport_arc.clone());
                            udp_transports.push(transport_arc);
                            logger.log(LogLevel::Info, "Runtime", &format!("Bound udp transport on {}", actual_addr));
                        }
                    }
                }
            }
        }

        // 3. Initialize SD state machine with listeners
        let mut sd = ServiceDiscovery::new();
        for alias in &iface_aliases {
            let iface_cfg = sys_config.interfaces.get(alias).unwrap();
            let sd_cfg = if let Some(ref s) = iface_cfg.sd { s } else { continue; };
            
            let v4_ep = sd_cfg.endpoint_v4.as_ref().and_then(|name| iface_cfg.endpoints.get(name));
            let v6_ep = sd_cfg.endpoint_v6.as_ref().and_then(|name| iface_cfg.endpoints.get(name));
            
            if v4_ep.is_none() && v6_ep.is_none() { continue; }

            // Find local unicast IP for this interface
            let local_ip_v4 = iface_cfg.endpoints.values()
                .find(|e| e.version == 4 && e.ip.parse::<IpAddr>().map(|a| !a.is_multicast()).unwrap_or(false))
                .and_then(|e| e.ip.parse::<Ipv4Addr>().ok());
            
            let local_ip_v6 = iface_cfg.endpoints.values()
                .find(|e| e.version == 6 && e.ip.parse::<IpAddr>().map(|a| !a.is_multicast()).unwrap_or(false))
                .and_then(|e| e.ip.parse::<Ipv6Addr>().ok());

            let mut transport_v4 = None;
            let mut mcast_v4 = None;
            if let Some(ep) = v4_ep {
                // Determine bind IP: 
                // 1. Instance-level unicast_bind for this interface
                // 2. First Unicast Endpoint or Local IP
                // 3. Local unicast IP
                let instance_bind_ip = instance_config.unicast_bind.get(alias)
                    .and_then(|name| iface_cfg.endpoints.get(name))
                    .and_then(|e| e.ip.parse::<Ipv4Addr>().ok());

                let bind_ip = instance_bind_ip
                    .or(local_ip_v4);

                let bind_ip = if cfg!(target_os = "windows") { 
                    Ipv4Addr::UNSPECIFIED 
                } else { 
                    bind_ip.unwrap_or_else(|| {
                        let msg = format!("STRICT BINDING: No bind IP resolved for SD v4 on {}. Aborting.", alias);
                        logger.log(LogLevel::Error, "Runtime", &msg);
                        panic!("{}", msg);
                    })
                };

                let bind_addr = SocketAddr::new(IpAddr::V4(bind_ip), ep.port);
                let mcast_addr = SocketAddr::new(IpAddr::V4(ep.ip.parse::<Ipv4Addr>().unwrap()), ep.port);
                
                // Use iface_cfg.name for SO_BINDTODEVICE if available, else alias
                let if_name = if iface_cfg.name.is_empty() { alias.as_str() } else { iface_cfg.name.as_str() };

                if let Ok(t) = UdpTransport::new_multicast(bind_addr, mcast_addr, Some(if_name)) {
                    let _ = t.set_multicast_loop_v4(true);
                    let _ = t.set_multicast_ttl_v4(instance_config.sd.multicast_hops as u32);
                    if let (Some(lip), Ok(mip)) = (local_ip_v4, ep.ip.parse::<Ipv4Addr>()) {
                        let _ = t.join_multicast_v4(&mip, &lip);
                        let _ = t.set_multicast_if_v4(&lip);
                        mcast_v4 = Some(SocketAddr::new(IpAddr::V4(mip), ep.port));
                    }
                    transport_v4 = Some(t);
                }
            }

            let mut transport_v6 = None;
            let mut mcast_v6 = None;
            if let Some(ep) = v6_ep {
                let mcast_ip_v6 = ep.ip.parse::<Ipv6Addr>().unwrap_or_else(|e| {
                    logger.log(LogLevel::Error, "Runtime", &format!("Invalid IPv6 multicast address '{}': {}", ep.ip, e));
                    panic!("Invalid IPv6 multicast address");
                });
                
                // Determine bind IP
                let instance_bind_ip = instance_config.unicast_bind.get(alias)
                    .and_then(|name| iface_cfg.endpoints.get(name))
                    .and_then(|e| e.ip.parse::<Ipv6Addr>().ok());

                let bind_ip = instance_bind_ip.or(local_ip_v6);

                let bind_ip_v6_opt = if cfg!(target_os = "windows") { 
                    Some(Ipv6Addr::UNSPECIFIED)
                } else { 
                    bind_ip
                };

                if let Some(bind_ip_v6) = bind_ip_v6_opt {
                    let bind_addr = SocketAddr::new(IpAddr::V6(bind_ip_v6), ep.port);
                    let mcast_addr = SocketAddr::new(IpAddr::V6(mcast_ip_v6), ep.port);
                    let if_name = if iface_cfg.name.is_empty() { alias.as_str() } else { iface_cfg.name.as_str() };
                    
                    if let Ok(t) = UdpTransport::new_multicast(bind_addr, mcast_addr, Some(if_name)) {
                        let _ = t.set_multicast_loop_v6(true);
                        let _ = t.set_multicast_hops_v6(instance_config.sd.multicast_hops as u32);
                        // Need iface index
                        let idx = Self::resolve_iface_index(&iface_cfg.name);
                        let _ = t.join_multicast_v6(&mcast_ip_v6, idx);
                        let _ = t.set_multicast_if_v6(idx);
                        mcast_v6 = Some(SocketAddr::new(IpAddr::V6(mcast_ip_v6), ep.port));
                        transport_v6 = Some(t);
                    }
                }
            }

            sd.add_listener(SdListener {
                alias: alias.clone(),
                transport_v4,
                transport_v6,
                multicast_group_v4: mcast_v4,
                multicast_group_v6: mcast_v6,
                local_ip_v4,
                local_ip_v6,
            });
            logger.log(LogLevel::Info, "Runtime", &format!("SD listener added for interface '{}'", alias));
        }

        Arc::new(Self {
            udp_transports,
            tcp_transports,
            sd: Arc::new(Mutex::new(sd)),
            services: Arc::new(RwLock::new(HashMap::new())),
            running: Arc::new(AtomicBool::new(true)),
            config: Some(instance_config),
            endpoints: all_discovered_endpoints,
            bound_ports,
            pending_requests: Arc::new(Mutex::new(HashMap::new())),
            session_manager: Arc::new(Mutex::new(HashMap::new())),
            tp_reassembler: Arc::new(Mutex::new(crate::codec::tp::TpReassembler::new())),
            logger,
        })
    }

    fn resolve_iface_index(name: &str) -> u32 {
        if name.is_empty() { return 0; }
        // Heuristic or system call
        let idx = if name.to_lowercase().contains("lo") || name.to_lowercase().contains("loopback") {
             if cfg!(target_os = "windows") { 1 } else { 1 } // typical lo index
        } else {
             0 // fallback
        };
        // Print to stderr (since we don't have logger instance in static method easily) or just return
        // Note: For real fix we should use if_nametoindex.
        idx
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
                        // TCP: Connect to the discovered endpoint
                        match crate::transport::TcpTransport::connect(endpoint) {
                            Ok(client) => {
                                client.set_nonblocking(true).ok();
                                self.logger.log(LogLevel::Info, "Runtime",
                                    &format!("TCP connected to {}", endpoint));
                                Arc::new(client)
                            }
                            Err(e) => {
                                self.logger.log(LogLevel::Error, "Runtime",
                                    &format!("TCP connect to {} failed: {}", endpoint, e));
                                return None;
                            }
                        }
                    } else {
                        // UDP (or default)
                        self.logger.log(LogLevel::Info, "Runtime", &format!("Searching for UDP transport for {}, count={}", endpoint, self.udp_transports.len()));
                        for (i, t) in self.udp_transports.iter().enumerate() {
                            if let Ok(la) = t.local_addr() {
                                self.logger.log(LogLevel::Info, "Runtime", &format!("  [{}] local_addr={}", i, la));
                            }
                        }
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


    pub fn subscribe_eventgroup(&self, service_id: u16, instance_id: u16, eventgroup_id: u16, ttl: u32, iface_alias: &str) {
        let mut sd = self.sd.lock().unwrap();
        // Resolve ports from bound transports
        // This is a bit complex in multi-interface, we might need a better way to find the port
        // For now, use the first available transport's port for the given interface.
        let port_v4 = self.udp_transports.iter().find(|t| t.local_addr().map(|a| a.is_ipv4()).unwrap_or(false))
            .and_then(|t| t.local_addr().ok()).map(|a| a.port()).unwrap_or(0);
        let port_v6 = self.udp_transports.iter().find(|t| t.local_addr().map(|a| a.is_ipv6()).unwrap_or(false))
            .and_then(|t| t.local_addr().ok()).map(|a| a.port()).unwrap_or(0);
        
        sd.subscribe_eventgroup(service_id, instance_id, eventgroup_id, ttl, iface_alias, port_v4, port_v6);
        self.logger.log(LogLevel::Info, "Runtime", &format!("Subscribing to Service 0x{:04x} EventGroup {} on {} (v4: {}, v6: {})", service_id, eventgroup_id, iface_alias, port_v4, port_v6));
    }

    pub fn offer_service(&self, alias: &str, instance: Box<dyn RequestHandler>) {
        // Resolve Config
        let (service_id, major, minor, instance_id, offer_on, multicast_name) = if let Some(cfg) = &self.config {
            if let Some(prov_cfg) = cfg.providing.get(alias) {
                (prov_cfg.service_id, prov_cfg.major_version, prov_cfg.minor_version, prov_cfg.instance_id, prov_cfg.offer_on.clone(), prov_cfg.multicast.clone())
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
        
        // Register in SD for each relevant interface
        let mut sd = self.sd.lock().unwrap();
        
        // Provide on all interfaces defined in offer_on
        for (iface_alias, endpoint_name) in offer_on {
            let mut final_port = 0;
            let mut proto_id = 0x11;
            
            // Resolve the actual bound port for this endpoint.
            if let Some(ep) = self.endpoints.get(&endpoint_name) {
                 let protocol = ep.protocol.to_lowercase();
                 proto_id = if protocol == "tcp" { 0x06 } else { 0x11 };
                 // Use actual bound port (resolves ephemeral), fallback to config
                 final_port = self.bound_ports.get(&endpoint_name).copied().unwrap_or(ep.port);
            } else {
                 self.logger.log(LogLevel::Warn, "Runtime", &format!("Endpoint '{}' not found for service '{}' on '{}'", endpoint_name, alias, iface_alias));
            }

            // Resolve Multicast
            let multicast = if let Some(mcast_name) = multicast_name.as_ref() {
                if let Some(m_ep) = self.endpoints.get(mcast_name) {
                    if let Ok(m_ip) = m_ep.ip.parse::<std::net::IpAddr>() {
                        Some((m_ip, m_ep.port))
                    } else { None }
                } else { None }
            } else { None };

            sd.offer_service(service_id, instance_id, major, minor, &iface_alias, final_port, proto_id, multicast);
            self.logger.log(LogLevel::Info, "Runtime", &format!("Offered Service '{}' (0x{:04x}) on {} (port {}, proto 0x{:02x})", 
                alias, service_id, iface_alias, final_port, proto_id));
        }
    }

    pub fn register_notification_handler(&self, service_id: u16, handler: Box<dyn RequestHandler>) {
        let mut services = self.services.write().unwrap();
        services.insert(service_id, handler);
        self.logger.log(LogLevel::Info, "Runtime", &format!("Registered notification handler for Service 0x{:04x}", service_id));
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

        let mtu = 1400; 
        let header_len = 20; // 16 (Header) + 4 (TP)
        let max_segment_payload = (mtu - header_len) / 16 * 16;
        
        let transport = if target.is_ipv6() { self.get_transport_v6() } else { self.get_transport_v4() };
        let transport = transport.expect("Required transport (UDP) not found for target family");

        if payload.len() > max_segment_payload {
            let segments = crate::codec::tp::segment_payload(payload, max_segment_payload);
            for (tp_header, chunk) in segments {
                 let header = SomeIpHeader::new(service_id, method_id, 0, session_id, 0x20, (4 + chunk.len()) as u32);
                 let mut msg = header.serialize().to_vec();
                 msg.extend_from_slice(&tp_header.serialize());
                 msg.extend_from_slice(&chunk);
                 
                 if let Err(e) = transport.send(&msg, Some(target)) {
                     self.logger.log(LogLevel::Error, "Runtime", &format!("Failed to send TP segment: {}", e));
                     let mut pending = self.pending_requests.lock().unwrap();
                     pending.remove(&(service_id, method_id, session_id));
                     return None;
                 }
                 // Flow control
                 thread::sleep(Duration::from_micros(100));
            }
        } else {
            let header = SomeIpHeader::new(service_id, method_id, 0, session_id, 0x00, payload.len() as u32);
            let mut msg = header.serialize().to_vec();
            msg.extend_from_slice(payload);
            
            if let Err(e) = transport.send(&msg, Some(target)) {
                self.logger.log(LogLevel::Error, "Runtime", &format!("Failed to send request: {}", e));
                let mut pending = self.pending_requests.lock().unwrap();
                pending.remove(&(service_id, method_id, session_id));
                return None;
            }
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
                            // Check for TP
                            let mt = header.message_type_enum();
                            let is_tp = mt.map(|m| m.uses_tp()).unwrap_or(false);
                            
                            let mut payload = &buf[16..size];
                            let mut allocated_payload: Option<Vec<u8>> = None;
                            
                            if is_tp {
                                // TP packet structure: Header (16) + TpHeader (4) + Payload
                                // Check size
                                if size < 20 {
                                     self.logger.log(LogLevel::Warn, "Runtime", "Received TP packet too short");
                                     continue;
                                }
                                
                                if let Ok(tp_header) = crate::codec::tp::TpHeader::deserialize(&buf[16..20]) {
                                    let segment_payload = &buf[20..size];
                                    let mut reassembler = self.tp_reassembler.lock().unwrap();
                                    match reassembler.process_segment(
                                        (header.service_id as u32) << 16 | header.method_id as u32, 
                                        (header.client_id as u32) << 16 | header.session_id as u32, 
                                        &tp_header, 
                                        segment_payload
                                    ) {
                                        Ok(Some(full_payload)) => {
                                            self.logger.log(LogLevel::Info, "Runtime", &format!("Reassembled TP message: {} bytes", full_payload.len()));
                                            allocated_payload = Some(full_payload);
                                        },
                                        Ok(None) => {
                                            // Stored, waiting for more
                                            continue;
                                        },
                                        Err(e) => {
                                            self.logger.log(LogLevel::Error, "Runtime", &format!("TP Reassembly Error: {}", e));
                                            continue;
                                        }
                                    }
                                } else {
                                     self.logger.log(LogLevel::Warn, "Runtime", "Failed to deserialize TP header");
                                     continue;
                                }
                            }

                            // Use reassembled payload if available, else original slice
                            let effective_payload = if let Some(ref p) = allocated_payload {
                                &p[..]
                            } else {
                                payload
                            };

                            self.logger.log(LogLevel::Debug, "Runtime", &format!("Received packet: Service 0x{:04x} Method 0x{:04x} Type 0x{:02x} Length {}", header.service_id, header.method_id, header.message_type, header.length));
                            #[cfg(feature = "packet-dump")]
                            header.dump(src);
                             // Handle RESPONSE (0x80) or TP Response (0xA0)
                             if header.message_type == 0x80 || header.message_type == 0xA0 {
                                 let mut pending = self.pending_requests.lock().unwrap();
                                 if let Some(tx) = pending.remove(&(header.service_id, header.method_id, header.session_id)) {
                                     let _ = tx.send(effective_payload.to_vec());
                                 }
                                 continue;
                             }
    
                             // Dispatch
                             let services = self.services.read().unwrap();
                             
                             // Handle Notification (0x02) or TP Notification (0x22)
                             if header.message_type == 0x02 || header.message_type == 0x22 {
                                 self.logger.log(LogLevel::Info, "Runtime", &format!("Received Notification: Service 0x{:04x} Event/Method 0x{:04x} Payload {} bytes", header.service_id, header.method_id, effective_payload.len()));
                                 if let Some(handler) = services.get(&header.service_id) {
                                     handler.handle(&header, effective_payload);
                                 }
                                 continue;
                             }
    
                             if let Some(handler) = services.get(&header.service_id) {
                                 // Request (0x00), RequestNoReturn (0x01), TP Request (0x20), TP ReqNoRet (0x21)
                                 let is_req = header.message_type == 0x00 || header.message_type == 0x20;
                                 let is_ff = header.message_type == 0x01 || header.message_type == 0x21;
                                 
                                 if is_req || is_ff {
                                     if let Some(res_payload) = handler.handle(&header, effective_payload) {
                                          if is_req {
                                              // Send Response
                                              let mtu = 1400; // Conservative MTU
                                              let header_len = 16 + 4; // SOME/IP + TP
                                              let max_segment_payload = (mtu - header_len) / 16 * 16; // Align to 16
                                              
                                              if res_payload.len() > max_segment_payload {
                                                  // Segmented Response
                                                  // Use 0xA0 (ResponseWithTp)
                                                  let segments = crate::codec::tp::segment_payload(&res_payload, max_segment_payload);
                                                  for (tp_header, chunk) in segments {
                                                      let msg_header = SomeIpHeader::new(
                                                          header.service_id,
                                                          header.method_id,
                                                          header.client_id,
                                                          header.session_id,
                                                          0xA0, // ResponseWithTp
                                                          (4 + chunk.len()) as u32 // Length covers TP Header + Payload
                                                      );
                                                      let mut msg = msg_header.serialize().to_vec();
                                                      msg.extend_from_slice(&tp_header.serialize());
                                                      msg.extend_from_slice(&chunk);
                                                      let _ = transport.send(&msg, Some(src));
                                                      // Small delay to avoid flooding UDP buffer
                                                      // std::thread::sleep(std::time::Duration::from_micros(100)); 
                                                  }
                                              } else {
                                                  // Standard Response
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
