use super::packet::SdPacket;
use super::entries::{SdEntry, EntryType};
use super::options::SdOption;
use crate::transport::{UdpTransport, SomeIpTransport};
use crate::codec::{SomeIpSerialize, SomeIpDeserialize, SomeIpHeader};
use std::net::{SocketAddr, Ipv4Addr};
use std::collections::HashMap;
use std::time::{Instant, Duration, SystemTime, UNIX_EPOCH};
use std::io::ErrorKind;

#[derive(Debug, Clone, Copy, PartialEq)]
enum ServicePhase {
    Down,
    InitialWait,
    Repetition,
    Main,
}

#[derive(Debug, Clone)]
struct LocalService {
    entry: SdEntry, // Template entry
    endpoint_options: Vec<SdOption>,
    phase: ServicePhase,
    
    // Timer state
    phase_start: Instant,
    next_transmission: Instant,
    repetition_count: u32,

    // Config
    initial_delay_min: Duration,
    initial_delay_max: Duration,
    repetition_base_delay: Duration,
    repetition_max: u32,
    cyclic_delay: Duration,
}

impl LocalService {
    fn new(entry: SdEntry, options: Vec<SdOption>) -> Self {
        LocalService {
            entry,
            endpoint_options: options,
            phase: ServicePhase::Down,
            phase_start: Instant::now(),
            next_transmission: Instant::now() + Duration::from_secs(3600), // Far future
            repetition_count: 0,
            
            // Default Config (Autosar CP R20-11)
            initial_delay_min: Duration::from_millis(10),
            initial_delay_max: Duration::from_millis(100),
            repetition_base_delay: Duration::from_millis(100),
            repetition_max: 3,
            cyclic_delay: Duration::from_secs(1),
        }
    }

    fn transition_to_initial_wait(&mut self) {
        self.phase = ServicePhase::InitialWait;
        self.phase_start = Instant::now();
        
        // Random delay
        let range = (self.initial_delay_max.as_millis() - self.initial_delay_min.as_millis()) as u64;
        let now_nanos = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().subsec_nanos() as u64;
        let random_millis = self.initial_delay_min.as_millis() as u64 + (now_nanos % range);
        
        self.next_transmission = Instant::now() + Duration::from_millis(random_millis);
    }

    fn transition_to_repetition(&mut self) {
        self.phase = ServicePhase::Repetition;
        self.phase_start = Instant::now();
        self.repetition_count = 0;
        self.next_transmission = Instant::now(); // Send immediately upon entering
    }

    fn transition_to_main(&mut self) {
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
    local_services: HashMap<(u16, u16), LocalService>, // (ServiceId, InstanceId) -> Service
    remote_services: HashMap<(u16, u16), RemoteService>,
}

impl ServiceDiscovery {
    pub fn new(transport: UdpTransport, multicast_group: SocketAddr) -> Self {
        // Try to set non-blocking
        let _ = transport.set_nonblocking(true);
        
        ServiceDiscovery {
            transport,
            multicast_group,
            local_services: HashMap::new(),
            remote_services: HashMap::new(),
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

        // Determine IPv4/IPv6 from transport local addr?
        // For MVP, assume IPv4 127.0.0.1 or similar, or let user pass it.
        // TODO: Resolve actual IP.
        let option = SdOption::Ipv4Endpoint {
            address: Ipv4Addr::new(127, 0, 0, 1),
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
                     // We need to calculate TTL.
                     // Default 0xFFFF00 (as 24bit) => 0x00FFFFFF
                     let mut entry = service.entry.clone();
                     entry.ttl = 0x00FFFFFF;
                     
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
                     let _header_buf = &buf[0..16];
                     // ... Validation ...
                     
                     // Helper to parse header?
                     // Let's trust it's SD for now.
                     // Payload starts at 16.
                     if len > 16 {
                        let mut payload_reader = &buf[16..len];
                        if let Ok(packet) = SdPacket::deserialize(&mut payload_reader) {
                            self.handle_incoming_packet(packet);
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
                        
                        self.remote_services.insert((entry.service_id, entry.instance_id), remote);
                    }
                },
                EntryType::FindService => {
                    // TODO: Send Offer if we have it?
                },
                _ => {}
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

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
        let mut sd = ServiceDiscovery::new(transport, multicast);

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

