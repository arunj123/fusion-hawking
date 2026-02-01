use super::traits::SomeIpTransport;
use std::net::{UdpSocket, SocketAddr, Ipv4Addr};
use std::io::Result;

pub struct UdpTransport {
    socket: UdpSocket,
}

impl UdpTransport {
    pub fn new(bind_addr: SocketAddr) -> Result<Self> {
        let socket = UdpSocket::bind(bind_addr)?;
        Ok(UdpTransport { socket })
    }
    
    pub fn try_clone(&self) -> Result<Self> {
         Ok(UdpTransport { socket: self.socket.try_clone()? })
    }

    pub fn set_nonblocking(&self, nonblocking: bool) -> Result<()> {
        self.socket.set_nonblocking(nonblocking)
    }

    pub fn join_multicast_v4(&self, multiaddr: &Ipv4Addr, interface: &Ipv4Addr) -> Result<()> {
        self.socket.join_multicast_v4(multiaddr, interface)
    }
}

impl SomeIpTransport for UdpTransport {
    fn send(&self, data: &[u8], destination: Option<SocketAddr>) -> Result<usize> {
        if let Some(dest) = destination {
            self.socket.send_to(data, dest)
        } else {
            // UDP requires a destination if not connected.
            // For this implementation, we expect a destination.
             Err(std::io::Error::new(std::io::ErrorKind::InvalidInput, "UDP requires a destination address"))
        }
    }

    fn receive(&self, buffer: &mut [u8]) -> Result<(usize, SocketAddr)> {
        self.socket.recv_from(buffer)
    }

    fn local_addr(&self) -> Result<SocketAddr> {
        self.socket.local_addr()
    }
}
