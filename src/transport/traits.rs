use std::io::Result;
use std::net::SocketAddr;

/// Trait representing a SOME/IP transport channel.
/// Designed to be object-safe and pluggable (e.g. for TLS or Mocking).
pub trait SomeIpTransport: Send + Sync {
    /// Send data to the connected peer (TCP) or configured destination (UDP).
    /// For UDP, this might default to the last received address or a fixed target.
    fn send(&self, data: &[u8], destination: Option<SocketAddr>) -> Result<usize>;

    /// Receive data from the network.
    /// Returns the number of bytes read and the source address.
    fn receive(&self, buffer: &mut [u8]) -> Result<(usize, SocketAddr)>;
    
    /// Get the local socket address.
    fn local_addr(&self) -> Result<SocketAddr>;
}
