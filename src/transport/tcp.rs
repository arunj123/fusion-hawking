use super::traits::SomeIpTransport;
use std::net::{TcpStream, SocketAddr};
use std::io::{Result, Read, Write};

pub struct TcpTransport {
    stream: TcpStream,
}

impl TcpTransport {
    pub fn new(stream: TcpStream) -> Self {
        TcpTransport { stream }
    }
}

impl SomeIpTransport for TcpTransport {
    fn send(&self, data: &[u8], _destination: Option<SocketAddr>) -> Result<usize> {
        // TCP is connection-oriented, destination is implicit.
        // We need mutable access to write to TcpStream, usually.
        // BUT, TcpStream reference impls Read/Write.
        // Wait, &TcpStream implements Read/Write? Yes.
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
