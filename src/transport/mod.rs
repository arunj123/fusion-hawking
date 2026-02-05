//! # Transport Layer Module
//!
//! Provides network transport abstractions for SOME/IP communication.
//!
//! ## Key Types
//!
//! - [`SomeIpTransport`] - Trait for send/receive operations
//! - [`UdpTransport`] - UDP transport with multicast support
//! - [`TcpTransport`] - TCP client for point-to-point connections
//! - [`TcpServer`] - TCP server for accepting connections
//!
//! ## Example
//!
//! ```ignore
//! use fusion_hawking::transport::UdpTransport;
//!
//! let transport = UdpTransport::bind(30490).unwrap();
//! transport.join_multicast("224.0.0.1".parse().unwrap()).unwrap();
//! ```

pub mod traits;
pub mod udp;
pub mod tcp;

pub use traits::*;
pub use udp::*;
pub use tcp::*;
