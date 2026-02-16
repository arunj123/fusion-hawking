use super::packet::SdPacket;
use super::entries::{SdEntry, EntryType};
use super::options::SdOption;
use crate::transport::{UdpTransport, SomeIpTransport};
use crate::codec::{SomeIpSerialize, SomeIpDeserialize, SomeIpHeader};
use crate::runtime::config::SdConfig;
use std::net::{SocketAddr, Ipv4Addr};
use std::collections::HashMap;
use std::time::{Instant, Duration, SystemTime, UNIX_EPOCH};

pub const DEFAULT_SD_PORT: u16 = 30490;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ServicePhase {
    /// [PRS_SOMEIPSD_00011] Down Phase
    Down,
    /// [PRS_SOMEIPSD_00012] Initial Wait Phase
    InitialWait,
    /// [PRS_SOMEIPSD_00013] Repetition Phase
    Repetition,
    /// [PRS_SOMEIPSD_00014] Main Phase
    Main,
}

#[derive(Debug, Clone)]
pub(crate) struct LocalService {
    pub entry: SdEntry, // Template entry
    pub endpoint_options: Vec<SdOption>,
    pub phase: ServicePhase,
    
    // Timer state
    pub phase_start: Instant,
    pub next_transmission: Instant,
    pub repetition_count: u32,

    // Config (from SdConfig)
    initial_delay_min: Duration,
    initial_delay_max: Duration,
    repetition_base_delay: Duration,
    repetition_max: u32,
    cyclic_delay: Duration,
    pub ttl: u32,
}

impl LocalService {
    /// Create with default configuration
    pub(crate) fn new(entry: SdEntry, options: Vec<SdOption>) -> Self {
        Self::with_config(entry, options, &SdConfig::default())
    }
    
    /// Create with custom configuration from SdConfig
    pub(crate) fn with_config(entry: SdEntry, options: Vec<SdOption>, config: &SdConfig) -> Self {
        LocalService {
            entry,
            endpoint_options: options,
            phase: ServicePhase::Down,
            phase_start: Instant::now(),
            next_transmission: Instant::now() + Duration::from_secs(3600), // Far future
            repetition_count: 0,
            
            // Config from SdConfig
            initial_delay_min: Duration::from_millis(config.initial_delay_min_ms),
            initial_delay_max: Duration::from_millis(config.initial_delay_max_ms),
            repetition_base_delay: Duration::from_millis(config.repetition_base_delay_ms),
            repetition_max: config.repetition_max,
            cyclic_delay: Duration::from_millis(config.cyclic_delay_ms),
            ttl: config.ttl,
        }
    }

    /// [PRS_SOMEIPSD_00012] Initial Wait Phase
    pub(crate) fn transition_to_initial_wait(&mut self) {
        self.phase = ServicePhase::InitialWait;
        self.phase_start = Instant::now();
        
        // Random delay between min and max
        let range = self.initial_delay_max.as_millis().saturating_sub(self.initial_delay_min.as_millis()) as u64;
        let range = if range == 0 { 1 } else { range };
        let now_nanos = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().subsec_nanos() as u64;
        let random_millis = self.initial_delay_min.as_millis() as u64 + (now_nanos % range);
        
        self.next_transmission = Instant::now() + Duration::from_millis(random_millis);
    }

    /// [PRS_SOMEIPSD_00013] Repetition Phase
    pub(crate) fn transition_to_repetition(&mut self) {
        self.phase = ServicePhase::Repetition;
        self.phase_start = Instant::now();
        self.repetition_count = 0;
        self.next_transmission = Instant::now(); // Send immediately upon entering
    }

    /// [PRS_SOMEIPSD_00014] Main Phase
    pub(crate) fn transition_to_main(&mut self) {
        self.phase = ServicePhase::Main;
        self.phase_start = Instant::now();
        self.next_transmission = Instant::now(); 
    }
}

#[derive(Debug, Clone)]
pub struct RemoteService {
    pub service_id: u16,
    pub instance_id: u16,
    pub version_major: u8,
    pub version_minor: u32,
    pub endpoint: Vec<SdOption>, // could be multiple options
    pub last_seen: Instant,
    pub ttl: u32,
}

#[derive(Debug)]
pub struct SdListener {
    pub alias: String,
    pub transport_v4: Option<UdpTransport>,
    pub transport_v6: Option<UdpTransport>,
    pub multicast_group_v4: Option<SocketAddr>,
    pub multicast_group_v6: Option<SocketAddr>,
    pub local_ip_v4: Option<Ipv4Addr>,
    pub local_ip_v6: Option<std::net::Ipv6Addr>,
}

pub struct ServiceDiscovery {
    pub(crate) listeners: HashMap<String, SdListener>,
    pub(crate) local_services: HashMap<(u16, u16), LocalService>, // (ServiceId, InstanceId) -> Service
    pub(crate) remote_services: HashMap<(u16, u16), RemoteService>,
    // Event subscriptions: (ServiceId, EventgroupId) -> list of subscriber endpoints
    pub(crate) subscriptions: HashMap<(u16, u16), Vec<SocketAddr>>,
    pub(crate) pending_subscriptions: HashMap<(u16, u16), bool>,
}

impl ServiceDiscovery {
    pub fn new() -> Self {
        ServiceDiscovery {
            listeners: HashMap::new(),
            local_services: HashMap::new(),
            remote_services: HashMap::new(),
            subscriptions: HashMap::new(),
            pending_subscriptions: HashMap::new(),
        }
    }

    pub fn add_listener(&mut self, listener: SdListener) {
        if let Some(ref t4) = listener.transport_v4 {
            let _ = t4.set_nonblocking(true);
        }
        if let Some(ref t6) = listener.transport_v6 {
            let _ = t6.set_nonblocking(true);
        }
        self.listeners.insert(listener.alias.clone(), listener);
    }

    pub fn offer_service(&mut self, service_id: u16, instance_id: u16, major: u8, minor: u32, iface_alias: &str, port: u16, proto: u8, multicast: Option<(std::net::IpAddr, u16)>) {
        let mut options = Vec::new();

        if let Some(listener) = self.listeners.get(iface_alias) {
            if let Some(ip_v4) = listener.local_ip_v4 {
                options.push(SdOption::Ipv4Endpoint {
                    address: ip_v4,
                    transport_proto: proto,
                    port,
                });
            }

            if let Some(ip_v6) = listener.local_ip_v6 {
                options.push(SdOption::Ipv6Endpoint {
                    address: ip_v6,
                    transport_proto: proto,
                    port,
                });
            }
        }

        if let Some((mcast_ip, mcast_port)) = multicast {
            match mcast_ip {
                std::net::IpAddr::V4(addr) => {
                    options.push(SdOption::Ipv4Multicast {
                        address: addr,
                        transport_proto: 0x11, // Always UDP for multicast
                        port: mcast_port,
                    });
                },
                std::net::IpAddr::V6(addr) => {
                    options.push(SdOption::Ipv6Multicast {
                        address: addr,
                        transport_proto: 0x11,
                        port: mcast_port,
                    });
                }
            }
        }

        let entry = SdEntry {
            entry_type: EntryType::OfferService,
            index_1: 0,
            index_2: 0,
            number_of_opts_1: options.len() as u8,
            number_of_opts_2: 0,
            service_id,
            instance_id,
            major_version: major,
            ttl: 0, // Will be set dynamically
            minor_version: minor,
        };

        let mut service = LocalService::new(entry, options);
        
        // Start phase: Initial Wait
        service.transition_to_initial_wait();
        
        self.local_services.insert((service_id, instance_id), service);
    }
    
    pub fn stop_offer_service(&mut self, service_id: u16, instance_id: u16) {
        // We need to mutate the service phase, then send a packet.
        // To avoid borrow issues, we separate the actions.
        let mut entry_to_send = None;
        let mut options_to_send = Vec::new();

        if let Some(service) = self.local_services.get_mut(&(service_id, instance_id)) {
            service.phase = ServicePhase::Down;
            // Capture data for sending
            entry_to_send = Some(service.entry.clone());
            options_to_send = service.endpoint_options.clone();
        }

        if let Some(mut entry) = entry_to_send {
            // TTL 0 for StopOffer
            entry.ttl = 0;
            let _ = self.send_packet(entry, options_to_send);
        }
    }
    
    pub fn find_service(&self, service_id: u16, instance_id: u16) -> Option<&RemoteService> {
        self.remote_services.get(&(service_id, instance_id))
    }
    
    pub fn get_service(&self, service_id: u16, instance_id: u16) -> Option<(SocketAddr, u8)> {
        // [PRS_SOMEIPSD_00282] If instance_id is 0xFFFF, return first matching service_id
        if instance_id == 0xFFFF {
            for ((sid, _), remote) in &self.remote_services {
                if *sid == service_id {
                     for opt in &remote.endpoint {
                         if let SdOption::Ipv4Endpoint { address, port, transport_proto } = opt {
                             return Some((SocketAddr::new(std::net::IpAddr::V4(*address), *port), *transport_proto));
                         }
                         if let SdOption::Ipv6Endpoint { address, port, transport_proto } = opt {
                             return Some((SocketAddr::new(std::net::IpAddr::V6(*address), *port), *transport_proto));
                         }
                     }
                }
            }
        } else {
            if let Some(remote) = self.remote_services.get(&(service_id, instance_id)) {
                 for opt in &remote.endpoint {
                     if let SdOption::Ipv4Endpoint { address, port, transport_proto } = opt {
                         return Some((SocketAddr::new(std::net::IpAddr::V4(*address), *port), *transport_proto));
                     }
                     if let SdOption::Ipv6Endpoint { address, port, transport_proto } = opt {
                         return Some((SocketAddr::new(std::net::IpAddr::V6(*address), *port), *transport_proto));
                     }
                 }
            }
        }
        None
    }

    pub fn subscribe_eventgroup(&mut self, service_id: u16, instance_id: u16, eventgroup_id: u16, ttl: u32, iface_alias: &str, port_v4: u16, port_v6: u16) {
        let entry = SdEntry {
            entry_type: EntryType::SubscribeEventgroup,
            index_1: 0,
            index_2: 0,
            number_of_opts_1: 2,  
            number_of_opts_2: 0,
            service_id,
            instance_id,
            major_version: 0x01,
            ttl,
            minor_version: (eventgroup_id as u32) << 16,
        };

        let mut opts = Vec::new();
        if let Some(listener) = self.listeners.get(iface_alias) {
            if let Some(ip_v4) = listener.local_ip_v4 {
                opts.push(SdOption::Ipv4Endpoint {
                    address: ip_v4,
                    transport_proto: 0x11, // UDP
                    port: port_v4,
                });
            }
            if let Some(ip_v6) = listener.local_ip_v6 {
                opts.push(SdOption::Ipv6Endpoint {
                    address: ip_v6,
                    transport_proto: 0x11,
                    port: port_v6,
                });
            }
        }

        self.pending_subscriptions.insert((service_id, eventgroup_id), false);
        let _ = self.send_packet(entry, opts);
    }

    /// Unsubscribe from an eventgroup (sends SubscribeEventgroup with TTL=0).
    pub fn unsubscribe_eventgroup(&mut self, service_id: u16, instance_id: u16, eventgroup_id: u16, iface_alias: &str) {
        self.subscribe_eventgroup(service_id, instance_id, eventgroup_id, 0, iface_alias, 0, 0);
        self.pending_subscriptions.remove(&(service_id, eventgroup_id));
    }

    /// Check if subscription was acknowledged.
    pub fn is_subscription_acked(&self, service_id: u16, eventgroup_id: u16) -> bool {
        self.pending_subscriptions.get(&(service_id, eventgroup_id)).copied().unwrap_or(false)
    }

    pub fn poll(&mut self) {
        let now = Instant::now();
        let mut packets_to_send = Vec::new();

        // 1. Process Outgoing (Local Services)
        for (_, service) in self.local_services.iter_mut() {
            if service.phase == ServicePhase::Down {
                continue;
            }

            if now >= service.next_transmission {
                let mut should_send = false;
                
                // Determine if we should send based on phase logic
                match service.phase {
                    ServicePhase::InitialWait => {
                        // Mistake in previous edit: `service.transition_to_repetition()`!
                        // Let's fix it here properly.
                        service.transition_to_repetition();
                        should_send = true; 
                    }
                    ServicePhase::Repetition => {
                        should_send = true;
                        service.repetition_count += 1;
                        if service.repetition_count > service.repetition_max {
                            service.transition_to_main();
                        } else {
                            // Schedule next repetition
                            let multiplier = 2u32.pow(service.repetition_count - 1);
                            let delay = service.repetition_base_delay * multiplier;
                            service.next_transmission = now + delay;
                        }
                    }
                    ServicePhase::Main => {
                        should_send = true;
                        service.next_transmission = now + service.cyclic_delay;
                    }
                    _ => {}
                }
                
                if should_send {
                     // Use configured TTL from service
                     let mut entry = service.entry.clone();
                     entry.ttl = service.ttl;
                     
                     // Update Option Referencing
                     // We are sending 1 entry with all options.
                     // So options start at index 0.
                     entry.index_1 = 0;
                     entry.number_of_opts_1 = service.endpoint_options.len() as u8;
                     entry.index_2 = 0;
                     entry.number_of_opts_2 = 0;
                     
                     packets_to_send.push((entry, service.endpoint_options.clone()));
                }
            }
        }

        // Send accumulated packets
        for (entry, options) in packets_to_send {
            let _ = self.send_packet(entry, options);
        }

        // 2. Process Incoming
        let mut incoming_packets = Vec::new();

        // Separate transport polling to avoid borrow conflict
        {
            let mut buf = [0u8; 1500];
            for listener in self.listeners.values() {
                // Poll IPv4
                if let Some(ref t4) = listener.transport_v4 {
                    while let Ok((len, addr)) = t4.receive(&mut buf) {
                        if len > 16 {
                            let mut payload_reader = &buf[16..len];
                            if let Ok(packet) = SdPacket::deserialize(&mut payload_reader) {
                                #[cfg(feature = "packet-dump")]
                                packet.dump(addr);
                                incoming_packets.push(packet);
                            }
                        }
                    }
                }
                // Poll IPv6
                if let Some(ref t6) = listener.transport_v6 {
                    while let Ok((len, addr)) = t6.receive(&mut buf) {
                        if len > 16 {
                            let mut payload_reader = &buf[16..len];
                            if let Ok(packet) = SdPacket::deserialize(&mut payload_reader) {
                                #[cfg(feature = "packet-dump")]
                                packet.dump(addr);
                                incoming_packets.push(packet);
                            }
                        }
                    }
                }
            }
        }

        for packet in incoming_packets {
            self.handle_incoming_packet(packet);
        }
    }

    fn send_packet(&self, entry: SdEntry, options: Vec<SdOption>) -> std::io::Result<()> {
        let packet = SdPacket {
            flags: 0x80,
            entries: vec![entry],
            options,
        };

        let mut payload = Vec::new();
        packet.serialize(&mut payload)?;
        
        let header = SomeIpHeader::new(
            0xFFFF, 0x8100, 
            0x0000, 0x0001, 
            0x02, 
            payload.len() as u32
        );
        
        let mut message = Vec::new();
        message.extend_from_slice(&header.serialize());
        message.extend_from_slice(&payload);
        
        // Send on all listeners
        for listener in self.listeners.values() {
            if let Some(ref t4) = listener.transport_v4 {
                if let Some(mcast_v4) = listener.multicast_group_v4 {
                    let _ = t4.send(&message, Some(mcast_v4));
                }
            }
            if let Some(ref t6) = listener.transport_v6 {
                if let Some(mcast_v6) = listener.multicast_group_v6 {
                    let _ = t6.send(&message, Some(mcast_v6));
                }
            }
        }
        Ok(())
    }

    fn handle_incoming_packet(&mut self, packet: SdPacket) {
        // Iterate entries
        for entry in packet.entries {
            match entry.entry_type {
                EntryType::OfferService => {
                    if entry.ttl == 0 {
                        // Stop Offer -> Remove service
                        self.remote_services.remove(&(entry.service_id, entry.instance_id));
                    } else {
                        // Offer Service -> Add/Update
                        // We need to resolve options referenced by indices.
                        // SdEntry has index_1, index_2, num_opts_1, num_opts_2.
                        // This indicates a range in the options array.
                        // But SdPacket::options is a flat list.
                        // The indices are indices into the Options Array of the packet.
                        // We need to collect those options.
                        
                        let start_idx = entry.index_1 as usize; // Usually just index 1? Spec says "Index 1st option".
                        // Wait, spec says: "Index 1st Option run".
                        // And "Number of Options 1".
                        // It covers a range [index_1, index_1 + num_opts_1).
                        // And possibly a second range.
                        
                        let mut service_opts = Vec::new();
                        
                        // Range 1
                        let end_idx_1 = start_idx + entry.number_of_opts_1 as usize;
                        if end_idx_1 <= packet.options.len() {
                            for i in start_idx..end_idx_1 {
                                service_opts.push(packet.options[i].clone());
                            }
                        }
                        
                        // Range 2
                        let start_idx_2 = entry.index_2 as usize;
                        let end_idx_2 = start_idx_2 + entry.number_of_opts_2 as usize;
                        if end_idx_2 <= packet.options.len() {
                            for i in start_idx_2..end_idx_2 {
                                service_opts.push(packet.options[i].clone());
                            }
                        }

                        let remote = RemoteService {
                            service_id: entry.service_id,
                            instance_id: entry.instance_id,
                            version_major: entry.major_version,
                            version_minor: entry.minor_version,
                            endpoint: service_opts,
                            last_seen: Instant::now(),
                            ttl: entry.ttl,
                        };
                        

                        
                        self.remote_services.insert((entry.service_id, entry.instance_id), remote);
                    }
                },
                EntryType::FindService => {
                    // TODO: Send Offer if we have it?
                },
                EntryType::SubscribeEventgroup => {
                    // Someone is subscribing to our eventgroup
                    let eventgroup_id = (entry.minor_version >> 16) as u16;
                    
                    if entry.ttl == 0 {
                        // Unsubscribe
                        if let Some(_subscribers) = self.subscriptions.get_mut(&(entry.service_id, eventgroup_id)) {
                            // Remove this subscriber (would need source addr from packet)
                            // For now, just log
                        }
                    } else {
                        // Subscribe - extract subscriber endpoint from options
                        let start_idx = entry.index_1 as usize;
                        let end_idx = start_idx + entry.number_of_opts_1 as usize;
                        
                        if end_idx <= packet.options.len() {
                            for i in start_idx..end_idx {
                                let subscriber_addr = match &packet.options[i] {
                                    SdOption::Ipv4Endpoint { address, port, .. } => {
                                        Some(SocketAddr::new(std::net::IpAddr::V4(*address), *port))
                                    }
                                    SdOption::Ipv6Endpoint { address, port, .. } => {
                                        Some(SocketAddr::new(std::net::IpAddr::V6(*address), *port))
                                    }
                                    _ => None
                                };

                                if let Some(addr) = subscriber_addr {
                                    // Add to subscriptions
                                    self.subscriptions
                                        .entry((entry.service_id, eventgroup_id))
                                        .or_insert_with(Vec::new)
                                        .push(addr);
                                    
                                    // Send SubscribeEventgroupAck
                                    let ack_entry = SdEntry {
                                        entry_type: EntryType::SubscribeEventgroupAck,
                                        index_1: 0,
                                        index_2: 0,
                                        number_of_opts_1: 0,
                                        number_of_opts_2: 0,
                                        service_id: entry.service_id,
                                        instance_id: entry.instance_id,
                                        major_version: entry.major_version,
                                        ttl: entry.ttl,
                                        minor_version: entry.minor_version,
                                    };
                                    let _ = self.send_packet(ack_entry, vec![]);
                                }
                            }
                        }
                    }
                },
                EntryType::SubscribeEventgroupAck => {
                    // Our subscription was acknowledged
                    let eventgroup_id = (entry.minor_version >> 16) as u16;
                    if entry.ttl > 0 {
                        // ACK - mark subscription as active
                        self.pending_subscriptions.insert((entry.service_id, eventgroup_id), true);
                    } else {
                        // NACK - mark subscription as failed
                        self.pending_subscriptions.insert((entry.service_id, eventgroup_id), false);
                    }
                },
                _ => {}
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Ipv6Addr;

    fn create_dummy_entry() -> SdEntry {
        SdEntry {
            entry_type: EntryType::OfferService,
            index_1: 0, index_2: 0, number_of_opts_1: 0, number_of_opts_2: 0,
            service_id: 0x1234, instance_id: 1, major_version: 1, ttl: 0, minor_version: 0
        }
    }

    #[test]
    fn test_local_service_initial_state() {
        let entry = create_dummy_entry();
        let service = LocalService::new(entry, vec![]);
        assert_eq!(service.phase, ServicePhase::Down);
    }

    #[test]
    fn test_local_service_transitions() {
        let entry = create_dummy_entry();
        let mut service = LocalService::new(entry, vec![]);

        // Down -> InitialWait
        service.transition_to_initial_wait();
        assert_eq!(service.phase, ServicePhase::InitialWait);
        assert!(service.next_transmission > Instant::now());

        // InitialWait -> Repetition
        service.transition_to_repetition();
        assert_eq!(service.phase, ServicePhase::Repetition);
        assert_eq!(service.repetition_count, 0);

        // Repetition -> Main
        service.transition_to_main();
        assert_eq!(service.phase, ServicePhase::Main);
    }

    #[test]
    fn test_service_discovery_find() {
        let transport_v4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let transport_v6 = UdpTransport::new("[::]:0".parse().unwrap()).unwrap();
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let local_ip_v6 = Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1);
        let m_v4: std::net::SocketAddr = "127.0.0.1:30490".parse().unwrap();
        let m_v6: std::net::SocketAddr = "[::1]:30490".parse().unwrap();
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: Some(transport_v4),
            transport_v6: Some(transport_v6),
            multicast_group_v4: Some(m_v4),
            multicast_group_v6: Some(m_v6),
            local_ip_v4: Some(local_ip),
            local_ip_v6: Some(local_ip_v6),
        });

        let remote = RemoteService {
            service_id: 0x5678,
            instance_id: 1,
            version_major: 1,
            version_minor: 0,
            endpoint: vec![],
            last_seen: Instant::now(),
            ttl: 10,
        };
        
        sd.remote_services.insert((0x5678, 1), remote);

        let found = sd.find_service(0x5678, 1);
        assert!(found.is_some());
        assert_eq!(found.unwrap().service_id, 0x5678);

        let not_found = sd.find_service(0x9999, 1);
        assert!(not_found.is_none());
    }


    #[test]
    fn test_offer_timing_initial_wait() {
        let entry = create_dummy_entry();
        // Min 10ms, Max 100ms
        let config = SdConfig {
            initial_delay_min_ms: 10,
            initial_delay_max_ms: 100,
            ..Default::default()
        };
        
        let mut service = LocalService::with_config(entry, vec![], &config);
        service.transition_to_initial_wait();
        
        // Should be at least 10ms after phase start
        assert!(service.next_transmission >= service.phase_start + Duration::from_millis(10));
        // Should be at most 100ms after phase start
        assert!(service.next_transmission <= service.phase_start + Duration::from_millis(150));
    }

    #[test]
    fn test_repetition_logic() {
        let entry = create_dummy_entry();
        let mut service = LocalService::new(entry, vec![]);
        
        // Transition to repetition
        service.transition_to_repetition();
        assert_eq!(service.repetition_count, 0);
        // Should send immediately (or very close to now)
        assert!(service.next_transmission <= Instant::now() + Duration::from_millis(5));
    }

    #[test]
    fn test_ttl_expiry_removes_service() {
        let transport_v4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let transport_v6 = UdpTransport::new("[::]:0".parse().unwrap()).unwrap();
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let local_ip_v6 = Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1);
        let m_v4: std::net::SocketAddr = "127.0.0.1:30490".parse().unwrap();
        let m_v6: std::net::SocketAddr = "[::1]:30490".parse().unwrap();
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: Some(transport_v4),
            transport_v6: Some(transport_v6),
            multicast_group_v4: Some(m_v4),
            multicast_group_v6: Some(m_v6),
            local_ip_v4: Some(local_ip),
            local_ip_v6: Some(local_ip_v6),
        });
        
        // Add a remote service
        let remote = RemoteService {
            service_id: 0x1234,
            instance_id: 1,
            version_major: 1,
            version_minor: 0,
            endpoint: vec![],
            last_seen: Instant::now(),
            ttl: 10,
        };
        sd.remote_services.insert((0x1234, 1), remote);
        assert!(sd.find_service(0x1234, 1).is_some());
        
        // Simulate receiving an offer with TTL 0 (StopOffer)
        let entry = SdEntry {
            entry_type: EntryType::OfferService,
            index_1: 0, index_2: 0, number_of_opts_1: 0, number_of_opts_2: 0,
            service_id: 0x1234, instance_id: 1, major_version: 1, ttl: 0, minor_version: 0
        };
        let packet = SdPacket {
            flags: 0x00,
            entries: vec![entry],
            options: vec![],
        };
        
        sd.handle_incoming_packet(packet);
        
        // Service should be removed
        assert!(sd.find_service(0x1234, 1).is_none());
    }

    #[test]
    fn test_service_discovery_ipv4_only() {
        let transport_v4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let m_v4: std::net::SocketAddr = "127.0.0.1:30490".parse().unwrap();
        
        // IPv4 Only
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: Some(transport_v4),
            transport_v6: None,
            multicast_group_v4: Some(m_v4),
            multicast_group_v6: None,
            local_ip_v4: Some(local_ip),
            local_ip_v6: None,
        });
        
        sd.offer_service(0x1234, 1, 1, 0, "primary", 30500, 0x11, None);
        let services = sd.local_services.values().next().unwrap();
        // Should only have IPv4 option
        assert_eq!(services.endpoint_options.len(), 1);
        match &services.endpoint_options[0] {
            SdOption::Ipv4Endpoint { .. } => {},
            _ => panic!("Expected IPv4 option"),
        }
    }

    #[test]
    fn test_service_discovery_ipv6_only() {
        let transport_v6 = UdpTransport::new("[::1]:0".parse().unwrap()).unwrap();
        let local_ip_v6 = Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1);
        let m_v6: std::net::SocketAddr = "[::1]:30490".parse().unwrap();
        
        // IPv6 Only
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: None,
            transport_v6: Some(transport_v6),
            multicast_group_v4: None,
            multicast_group_v6: Some(m_v6),
            local_ip_v4: None,
            local_ip_v6: Some(local_ip_v6),
        });
        
        sd.offer_service(0x1234, 1, 1, 0, "primary", 30500, 0x11, None);
        let services = sd.local_services.values().next().unwrap();
        // Should only have IPv6 option
        assert_eq!(services.endpoint_options.len(), 1);
        match &services.endpoint_options[0] {
            SdOption::Ipv6Endpoint { .. } => {},
            _ => panic!("Expected IPv6 option"),
        }
    }

    #[test]
    fn test_service_discovery_dual_stack() {
        let t4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let t6 = UdpTransport::new("[::1]:0".parse().unwrap()).unwrap();
        let ip4 = Ipv4Addr::new(127, 0, 0, 1);
        let ip6 = Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1);
        let m4: std::net::SocketAddr = "127.0.0.1:30490".parse().unwrap();
        let m6: std::net::SocketAddr = "[::1]:30490".parse().unwrap();
        
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: Some(t4),
            transport_v6: Some(t6),
            multicast_group_v4: Some(m4),
            multicast_group_v6: Some(m6),
            local_ip_v4: Some(ip4),
            local_ip_v6: Some(ip6),
        });
        
        sd.offer_service(0x1234, 1, 1, 0, "primary", 30500, 0x11, None);
        let services = sd.local_services.values().next().unwrap();
        // Should have both
        assert_eq!(services.endpoint_options.len(), 2);
    }
}

