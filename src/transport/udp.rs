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
    
    /// Create a multicast-ready socket with SO_REUSEADDR for shared port binding
    pub fn new_multicast(bind_addr: SocketAddr) -> Result<Self> {
        use socket2::{Socket, Domain, Type, Protocol};
        
        let domain = match bind_addr {
            SocketAddr::V4(_) => Domain::IPV4,
            SocketAddr::V6(_) => Domain::IPV6,
        };
        
        let socket = Socket::new(domain, Type::DGRAM, Some(Protocol::UDP))?;
        
        // Set SO_REUSEADDR to allow multiple processes to bind
        socket.set_reuse_address(true)?;
        
        // On some platforms, also need SO_REUSEPORT
        #[cfg(not(windows))]
        socket.set_reuse_port(true)?;
        
        socket.bind(&bind_addr.into())?;
        
        Ok(UdpTransport { socket: socket.into() })
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
    
    pub fn set_multicast_if_v4(&self, interface: &Ipv4Addr) -> Result<()> {
        use socket2::SockRef;
        
        let sock_ref = SockRef::from(&self.socket);
        sock_ref.set_multicast_if_v4(interface)
    }
    
    pub fn set_multicast_loop_v4(&self, val: bool) -> Result<()> {
        self.socket.set_multicast_loop_v4(val)
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
