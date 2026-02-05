//! # SOME/IP-SD (Service Discovery) Module
//!
//! Implements the SOME/IP Service Discovery protocol for dynamic service
//! registration, discovery, and event subscription.
//!
//! ## Key Types
//!
//! - [`ServiceDiscovery`] - Main state machine for SD operations
//! - [`SdEntry`] - Service/Eventgroup offers and subscriptions
//! - [`SdOption`] - IPv4/IPv6 endpoints, configuration, load balancing
//! - [`LocalService`] / [`RemoteService`] - Service lifecycle management
//!
//! ## Service Phases
//!
//! Local services transition through phases: `Down` → `InitialWait` → `Repetition` → `Main`
//!
//! ## Example
//!
//! ```ignore
//! use fusion_hawking::sd::ServiceDiscovery;
//!
//! let mut sd = ServiceDiscovery::new(transport, multicast_addr, local_ip);
//! sd.offer_service(0x1001, 0x0001, 1, 0, 30490, 0x11); // UDP
//! sd.poll(); // Process incoming/outgoing announcements
//! ```

pub mod entries;
pub mod options;
pub mod packet;
pub mod machine;

pub use entries::*;
pub use options::*;
pub use packet::*;
pub use machine::*;

mod tests;
