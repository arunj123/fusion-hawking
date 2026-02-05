use super::packet::SdPacket;
use super::entries::{SdEntry, EntryType};
use super::options::SdOption;
use crate::transport::{UdpTransport, SomeIpTransport};
use crate::codec::{SomeIpSerialize, SomeIpDeserialize, SomeIpHeader};
use crate::runtime::config::SdConfig;
use std::net::{SocketAddr, Ipv4Addr};
use std::collections::HashMap;
use std::time::{Instant, Duration, SystemTime, UNIX_EPOCH};
use std::io::ErrorKind;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ServicePhase {
    Down,
    InitialWait,
    Repetition,
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

    pub(crate) fn transition_to_repetition(&mut self) {
        self.phase = ServicePhase::Repetition;
        self.phase_start = Instant::now();
        self.repetition_count = 0;
        self.next_transmission = Instant::now(); // Send immediately upon entering
    }

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

pub struct ServiceDiscovery {
    transport: UdpTransport,
    multicast_group: SocketAddr,
    pub(crate) local_services: HashMap<(u16, u16), LocalService>, // (ServiceId, InstanceId) -> Service
    pub(crate) remote_services: HashMap<(u16, u16), RemoteService>,
    // Event subscriptions: (ServiceId, EventgroupId) -> list of subscriber endpoints
    pub(crate) subscriptions: HashMap<(u16, u16), Vec<SocketAddr>>,
    // Pending subscription requests: (ServiceId, EventgroupId) -> callback/flag
    pub(crate) pending_subscriptions: HashMap<(u16, u16), bool>,
    pub local_ip: Ipv4Addr,
}

impl ServiceDiscovery {
    pub fn new(transport: UdpTransport, multicast_group: SocketAddr, local_ip: Ipv4Addr) -> Self {
        // Try to set non-blocking
        let _ = transport.set_nonblocking(true);
        
        ServiceDiscovery {
            transport,
            multicast_group,
            local_services: HashMap::new(),
            remote_services: HashMap::new(),
            subscriptions: HashMap::new(),
            pending_subscriptions: HashMap::new(),
            local_ip,
        }
    }

    pub fn offer_service(&mut self, service_id: u16, instance_id: u16, major: u8, minor: u32, port: u16, proto: u8) {
        let entry = SdEntry {
            entry_type: EntryType::OfferService,
            index_1: 0,
            index_2: 0,
            number_of_opts_1: 0,
            number_of_opts_2: 0,
            service_id,
            instance_id,
            major_version: major,
            ttl: 0, // Will be set dynamically
            minor_version: minor,
        };

        // Use configured local IP instead of hardcoded 127.0.0.1
        let option = SdOption::Ipv4Endpoint {
            address: self.local_ip,
            transport_proto: proto,
            port,
        };

        let mut service = LocalService::new(entry, vec![option]);
        
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
    
    pub fn get_service(&self, service_id: u16) -> Option<SocketAddr> {
        for ((sid, _), remote) in &self.remote_services {
            if *sid == service_id {
                 for opt in &remote.endpoint {
                     if let SdOption::Ipv4Endpoint { address, port, .. } = opt {
                         return Some(SocketAddr::new(std::net::IpAddr::V4(*address), *port));
                     }
                 }
            }
        }
        None
    }

    /// Subscribe to an eventgroup from a remote service.
    /// Sends a SubscribeEventgroup entry and waits for SubscribeEventgroupAck.
    pub fn subscribe_eventgroup(&mut self, service_id: u16, instance_id: u16, eventgroup_id: u16, ttl: u32, port: u16) {
        // Build SubscribeEventgroup entry
        // Note: For eventgroup entries, minor_version field is repurposed as (eventgroup_id << 16 | counter)
        let entry = SdEntry {
            entry_type: EntryType::SubscribeEventgroup,
            index_1: 0,
            index_2: 0,
            number_of_opts_1: 1,  // We'll include our endpoint option
            number_of_opts_2: 0,
            service_id,
            instance_id,
            major_version: 0x01,
            ttl,
            minor_version: (eventgroup_id as u32) << 16,  // eventgroup_id in upper 16 bits
        };

        // Include our local endpoint so the server knows where to send events
        let option = SdOption::Ipv4Endpoint {
            address: self.local_ip,
            transport_proto: 0x11, // UDP
            port,
        };

        self.pending_subscriptions.insert((service_id, eventgroup_id), false);
        let _ = self.send_packet(entry, vec![option]);
    }

    /// Unsubscribe from an eventgroup (sends SubscribeEventgroup with TTL=0).
    pub fn unsubscribe_eventgroup(&mut self, service_id: u16, instance_id: u16, eventgroup_id: u16) {
        self.subscribe_eventgroup(service_id, instance_id, eventgroup_id, 0, 0);
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
        // Read until WouldBlock
        loop {
            let mut buf = [0u8; 1500]; // Max MTUish
            match self.transport.receive(&mut buf) {
                Ok((len, _addr)) => {
                     // Parse SOME/IP Header (16 bytes)
                     if len < 16 { continue; }
                     // ... Validation ...
                     
                     // Helper to parse header?
                     // Let's trust it's SD for now.
                     // Payload starts at 16.
                     if len > 16 {
                        let mut payload_reader = &buf[16..len];
                        match SdPacket::deserialize(&mut payload_reader) {
                            Ok(packet) => {
                                // self.logger is not easily accessible here without self.
                                // But SdMachine is part of SomeIpRuntime.
                                // Actually, let's just use println for now.
                                // println!("[SD] Received packet with {} entries", packet.entries.len());
                                self.handle_incoming_packet(packet);
                            }
                            Err(_e) => {
                                // Silent fail for now
                            }
                        }
                     }
                }
                Err(ref e) if e.kind() == ErrorKind::WouldBlock => {
                    break;
                }
                Err(_) => {
                    break;
                }
            }
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
        
        // SD Header
        let header = SomeIpHeader::new(
            0xFFFF, 0x8100, 
            0x0000, 0x0001, 
            0x02, // Notification 
            payload.len() as u32
        );
        
        let mut message = Vec::new();
        message.extend_from_slice(&header.serialize());
        message.extend_from_slice(&payload);
        
        self.transport.send(&message, Some(self.multicast_group))?;
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
                        
                        // Note: SD machine doesn't have a logger, so we'll just use println for debugging
                        // but actually, we should probably pass a logger or just rely on runtime to log.
                        // For now, let's keep it silent but ensure it's correct.
                        // Actually, I'll add a println that will show up in the captured output if any.
                        println!("[SD] Discovered Service 0x{:04x}:{}", entry.service_id, entry.instance_id);
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
                                if let SdOption::Ipv4Endpoint { address, port, .. } = &packet.options[i] {
                                    let subscriber_addr = SocketAddr::new(std::net::IpAddr::V4(*address), *port);
                                    
                                    // Add to subscriptions
                                    self.subscriptions
                                        .entry((entry.service_id, eventgroup_id))
                                        .or_insert_with(Vec::new)
                                        .push(subscriber_addr);
                                    
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
        let multicast: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let transport = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let mut sd = ServiceDiscovery::new(transport, multicast, local_ip);

        let remote = RemoteService {
            service_id: 0x5678,
            instance_id: 1,
            version_major: 1,
            version_minor: 0,
            endpoint: vec![],
            last_seen: Instant::now(),
            ttl: 10,
        };

        // Accessing private field logic - wait, remote_services is private?
        // machine.rs definition: pub struct ServiceDiscovery { remote_services: HashMap ... }
        // Line 98: remote_services: HashMap <...>, // Private by default.
        // I cannot access it from tests module? 
        // "mod tests" is a child module, it can access private items of parent.
        // Yes, "use super::*;" allows access to private items.
        
        sd.remote_services.insert((0x5678, 1), remote);

        let found = sd.find_service(0x5678, 1);
        assert!(found.is_some());
        assert_eq!(found.unwrap().service_id, 0x5678);

        let not_found = sd.find_service(0x9999, 1);
        assert!(not_found.is_none());
    }
}

