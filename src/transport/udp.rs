use super::traits::SomeIpTransport;
use std::net::{UdpSocket, SocketAddr, Ipv4Addr};
use std::io::Result;

#[derive(Debug)]
pub struct UdpTransport {
    socket: UdpSocket,
}

impl UdpTransport {
    pub fn new(bind_addr: SocketAddr) -> Result<Self> {
        let socket = UdpSocket::bind(bind_addr)?;
        Ok(UdpTransport { socket })
    }
    
    /// Create a multicast-ready socket with SO_REUSEADDR for shared port binding
    pub fn new_multicast(bind_addr: SocketAddr, multicast_addr: SocketAddr, iface_name: Option<&str>) -> Result<Self> {
        use socket2::{Socket, Domain, Type, Protocol};
        
        // Logger not available here? We use println! for debug
        println!("[DEBUG] Creating multicast socket for {}", bind_addr);

        let domain = match bind_addr {
            SocketAddr::V4(_) => Domain::IPV4,
            SocketAddr::V6(_) => Domain::IPV6,
        };
        
        let socket = Socket::new(domain, Type::DGRAM, Some(Protocol::UDP))?;
        
        // Set SO_REUSEADDR to allow multiple processes to bind
        socket.set_reuse_address(true)?;
        println!("[DEBUG] SO_REUSEADDR set to true");

        // Enable Multicast Loopback so local processes (on same host) see these packets
        match bind_addr {
            SocketAddr::V4(_) => {
                socket.set_multicast_loop_v4(true)?;
                println!("[DEBUG] IP_MULTICAST_LOOP (v4) set to true");
            },
            SocketAddr::V6(_) => {
                socket.set_multicast_loop_v6(true)?;
                println!("[DEBUG] IP_MULTICAST_LOOP (v6) set to true");
            }
        }
        
        // On some platforms, also need SO_REUSEPORT
        #[cfg(all(unix, not(target_os = "solaris"), not(target_os = "illumos")))]
        socket.set_reuse_port(true)?;

        // Platform-specific binding logic
        #[cfg(windows)]
        {
            // Windows: Bind to Unicast Interface IP (Strict Binding supported here)
            println!("[DEBUG] Windows: Binding to Unicast IP {}", bind_addr);
            match socket.bind(&bind_addr.into()) {
                Ok(_) => {},
                Err(e) => {
                    println!("[ERROR] Failed to bind to {}: {:?}", bind_addr, e);
                    return Err(e);
                }
            }
        }

        #[cfg(unix)]
        {
            // Linux/Unix: Bind to Multicast Group IP to allow reception
            // Binding to Unicast blocks multicast packets on Linux
            let mcast_sock_addr = SocketAddr::new(multicast_addr.ip(), bind_addr.port());
            println!("[DEBUG] Linux: Binding to Multicast Group IP {}", mcast_sock_addr);
            
            // SO_BINDTODEVICE
            if let Some(ifname) = iface_name {
                 println!("[DEBUG] Linux: Setting SO_BINDTODEVICE to {}", ifname);
                 let bytes = ifname.as_bytes();
                 if let Err(e) = socket.bind_device(Some(bytes)) {
                     println!("[WARN] Failed to set SO_BINDTODEVICE: {:?}", e);
                 }
            }

            match socket.bind(&mcast_sock_addr.into()) {
                Ok(_) => {},
                Err(e) => {
                    println!("[ERROR] Failed to bind to {}: {:?}", mcast_sock_addr, e);
                    return Err(e);
                }
            }
        }
        
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

    pub fn join_multicast_v6(&self, multiaddr: &std::net::Ipv6Addr, interface: u32) -> Result<()> {
        self.socket.join_multicast_v6(multiaddr, interface)
    }
    
    pub fn set_multicast_if_v4(&self, interface: &Ipv4Addr) -> Result<()> {
        use socket2::SockRef;
        let sock_ref = SockRef::from(&self.socket);
        sock_ref.set_multicast_if_v4(interface)
    }

    pub fn set_multicast_if_v6(&self, interface_index: u32) -> Result<()> {
        use socket2::SockRef;
        let sock_ref = SockRef::from(&self.socket);
        sock_ref.set_multicast_if_v6(interface_index)
    }
    
    pub fn set_multicast_loop_v4(&self, val: bool) -> Result<()> {
        self.socket.set_multicast_loop_v4(val)
    }

    pub fn set_multicast_loop_v6(&self, val: bool) -> Result<()> {
        self.socket.set_multicast_loop_v6(val)
    }

    pub fn set_multicast_ttl_v4(&self, ttl: u32) -> Result<()> {
        use socket2::SockRef;
        let sock_ref = SockRef::from(&self.socket);
        sock_ref.set_multicast_ttl_v4(ttl)
    }

    pub fn set_multicast_hops_v6(&self, hops: u32) -> Result<()> {
        use socket2::SockRef;
        let sock_ref = SockRef::from(&self.socket);
        sock_ref.set_multicast_hops_v6(hops)
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

    fn set_nonblocking(&self, nonblocking: bool) -> Result<()> {
        self.socket.set_nonblocking(nonblocking)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    

    #[test]
    fn test_udp_send_receive_loopback() {
        let receiver = UdpTransport::new("127.0.0.1:0".parse().unwrap()).unwrap();
        let receiver_addr = receiver.local_addr().unwrap();
        
        let sender = UdpTransport::new("127.0.0.1:0".parse().unwrap()).unwrap();
        
        // Send data
        let msg = b"Hello UDP";
        sender.send(msg, Some(receiver_addr)).unwrap();
        
        // Receiver might need a moment or blocking read
        // It block by default
        let mut buf = [0u8; 128];
        let (len, src) = receiver.receive(&mut buf).unwrap();
        
        assert_eq!(len, msg.len());
        assert_eq!(&buf[..len], msg);
        // Src port is dynamic, but IP should match
        if let SocketAddr::V4(src_v4) = src {
            assert_eq!(src_v4.ip(), &Ipv4Addr::new(127, 0, 0, 1));
        }
    }

    #[test]
    fn test_nonblocking_mode() {
        let transport = UdpTransport::new("127.0.0.1:0".parse().unwrap()).unwrap();
        transport.set_nonblocking(true).unwrap();
        
        let mut buf = [0u8; 10];
        let result = transport.receive(&mut buf);
        
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().kind(), std::io::ErrorKind::WouldBlock);
    }
}
