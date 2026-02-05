use super::traits::SomeIpTransport;
use std::net::{TcpStream, TcpListener, SocketAddr};
use std::io::{Result, Read, Write, ErrorKind};
use std::collections::HashMap;

/// TCP client transport for SOME/IP
pub struct TcpTransport {
    stream: TcpStream,
}

impl TcpTransport {
    pub fn new(stream: TcpStream) -> Self {
        TcpTransport { stream }
    }
    
    /// Connect to a remote SOME/IP server
    pub fn connect(addr: SocketAddr) -> Result<Self> {
        let stream = TcpStream::connect(addr)?;
        Ok(TcpTransport { stream })
    }
    
    /// Set non-blocking mode
    pub fn set_nonblocking(&self, nonblocking: bool) -> Result<()> {
        self.stream.set_nonblocking(nonblocking)
    }
    
    /// Get peer address
    pub fn peer_addr(&self) -> Result<SocketAddr> {
        self.stream.peer_addr()
    }
}

impl SomeIpTransport for TcpTransport {
    fn send(&self, data: &[u8], _destination: Option<SocketAddr>) -> Result<usize> {
        (&self.stream).write(data)
    }

    fn receive(&self, buffer: &mut [u8]) -> Result<(usize, SocketAddr)> {
        let bytes_read = (&self.stream).read(buffer)?;
        let peer = self.stream.peer_addr()?;
        Ok((bytes_read, peer))
    }

    fn local_addr(&self) -> Result<SocketAddr> {
        self.stream.local_addr()
    }
}

/// TCP server for accepting SOME/IP connections
pub struct TcpServer {
    listener: TcpListener,
    connections: HashMap<SocketAddr, TcpStream>,
}

impl TcpServer {
    /// Create a new TCP server bound to the given address
    pub fn bind(addr: SocketAddr) -> Result<Self> {
        let listener = TcpListener::bind(addr)?;
        Ok(TcpServer {
            listener,
            connections: HashMap::new(),
        })
    }
    
    /// Set non-blocking mode for the listener
    pub fn set_nonblocking(&self, nonblocking: bool) -> Result<()> {
        self.listener.set_nonblocking(nonblocking)
    }
    
    /// Get the local address the server is bound to
    pub fn local_addr(&self) -> Result<SocketAddr> {
        self.listener.local_addr()
    }
    
    /// Accept a new connection (non-blocking if set)
    /// Returns the peer address if a connection was accepted
    pub fn accept(&mut self) -> Result<Option<SocketAddr>> {
        match self.listener.accept() {
            Ok((stream, addr)) => {
                self.connections.insert(addr, stream);
                Ok(Some(addr))
            }
            Err(e) if e.kind() == ErrorKind::WouldBlock => Ok(None),
            Err(e) => Err(e),
        }
    }
    
    /// Poll for new connections (non-blocking)
    pub fn poll_accept(&mut self) -> Vec<SocketAddr> {
        let mut new_connections = Vec::new();
        loop {
            match self.accept() {
                Ok(Some(addr)) => new_connections.push(addr),
                Ok(None) => break,
                Err(_) => break,
            }
        }
        new_connections
    }
    
    /// Send data to a specific connected client
    pub fn send_to(&mut self, data: &[u8], addr: &SocketAddr) -> Result<usize> {
        if let Some(stream) = self.connections.get_mut(addr) {
            stream.write(data)
        } else {
            Err(std::io::Error::new(ErrorKind::NotConnected, "Client not connected"))
        }
    }
    
    /// Receive data from a specific connected client
    pub fn receive_from(&mut self, buffer: &mut [u8], addr: &SocketAddr) -> Result<usize> {
        if let Some(stream) = self.connections.get_mut(addr) {
            stream.read(buffer)
        } else {
            Err(std::io::Error::new(ErrorKind::NotConnected, "Client not connected"))
        }
    }
    
    /// Remove a connection
    pub fn disconnect(&mut self, addr: &SocketAddr) {
        self.connections.remove(addr);
    }
    
    /// Get all connected client addresses
    pub fn connected_clients(&self) -> Vec<SocketAddr> {
        self.connections.keys().cloned().collect()
    }
    
    /// Get the number of connected clients
    pub fn connection_count(&self) -> usize {
        self.connections.len()
    }
}
