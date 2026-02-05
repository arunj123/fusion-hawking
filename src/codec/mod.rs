//! # SOME/IP Codec Module
//!
//! Provides serialization and deserialization of SOME/IP messages.
//!
//! ## Key Types
//!
//! - [`SomeIpHeader`] - 16-byte SOME/IP header with message metadata
//! - [`SomeIpSerialize`] / [`SomeIpDeserialize`] - Traits for payload encoding
//! - [`MessageType`] - Request, Response, Notification, Error types
//! - [`ReturnCode`] - Standard AUTOSAR return codes
//! - [`SessionIdManager`] - Thread-safe session ID generation
//!
//! ## Example
//!
//! ```ignore
//! use fusion_hawking::codec::{SomeIpHeader, SomeIpSerialize};
//!
//! let header = SomeIpHeader::new(0x1001, 0x01, 0x1234, 0x01, 0x00, 8);
//! let bytes = header.serialize();
//! ```

pub mod header;
pub mod traits;
pub mod primitives;
pub mod complex;
pub mod session;

pub use header::*;
pub use traits::{SomeIpSerialize, SomeIpDeserialize};
pub use header::{MessageType, ReturnCode};
pub use session::SessionIdManager;

mod tests;
