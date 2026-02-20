use super::traits::SomeIpTransport;
use std::net::{TcpStream, TcpListener, SocketAddr};
use std::io::{Result, Read, Write, ErrorKind};
use std::collections::HashMap;
use std::sync::Mutex;

/// Minimum bytes needed to read the SOME/IP length field (service_id + method_id + length).
const SOMEIP_HEADER_PREFIX: usize = 8;

/// Check if `buf` contains a complete SOME/IP message.
/// Returns `Some(total_len)` if complete, `None` otherwise.
fn someip_message_len(buf: &[u8]) -> Option<usize> {
    if buf.len() < SOMEIP_HEADER_PREFIX {
        return None;
    }
    let length = u32::from_be_bytes([buf[4], buf[5], buf[6], buf[7]]) as usize;
    let total = SOMEIP_HEADER_PREFIX + length;
    if buf.len() >= total { Some(total) } else { None }
}

/// TCP client transport for SOME/IP
pub struct TcpTransport {
    stream: TcpStream,
    /// Internal buffer for accumulating partial SOME/IP messages.
    recv_buf: Mutex<Vec<u8>>,
}

impl TcpTransport {
    pub fn new(stream: TcpStream) -> Self {
        TcpTransport { stream, recv_buf: Mutex::new(Vec::new()) }
    }
    
    /// Connect to a remote SOME/IP server
    pub fn connect(addr: SocketAddr) -> Result<Self> {
        let stream = TcpStream::connect(addr)?;
        Ok(TcpTransport { stream, recv_buf: Mutex::new(Vec::new()) })
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
        let peer = self.stream.peer_addr()?;
        // Read whatever is available into the internal buffer
        let mut tmp = [0u8; 4096];
        match (&self.stream).read(&mut tmp) {
            Ok(0) => return Err(std::io::Error::new(ErrorKind::ConnectionReset, "Connection closed")),
            Ok(n) => { self.recv_buf.lock().unwrap().extend_from_slice(&tmp[..n]); }
            Err(e) if e.kind() == ErrorKind::WouldBlock => {}
            Err(e) => return Err(e),
        }
        // Check if we have a complete SOME/IP message
        let mut buf_ref = self.recv_buf.lock().unwrap();
        if let Some(msg_len) = someip_message_len(&buf_ref) {
            let copy_len = msg_len.min(buffer.len());
            buffer[..copy_len].copy_from_slice(&buf_ref[..copy_len]);
            buf_ref.drain(..msg_len);
            Ok((copy_len, peer))
        } else {
            Err(std::io::Error::new(ErrorKind::WouldBlock, "Incomplete SOME/IP message"))
        }
    }

    fn local_addr(&self) -> Result<SocketAddr> {
        self.stream.local_addr()
    }

    fn set_nonblocking(&self, nonblocking: bool) -> Result<()> {
        self.stream.set_nonblocking(nonblocking)
    }
}

/// A wrapper for TcpServer that implements SomeIpTransport trait
/// to be used in the SomeIpRuntime.
pub struct TcpServerTransport {
    server: Mutex<TcpServer>,
}

impl TcpServerTransport {
    pub fn new(server: TcpServer) -> Self {
        TcpServerTransport {
            server: Mutex::new(server),
        }
    }
}


impl SomeIpTransport for TcpServerTransport {
    fn send(&self, data: &[u8], destination: Option<SocketAddr>) -> Result<usize> {
        let mut server = self.server.lock().unwrap();
        if let Some(dest) = destination {
            server.send_to(data, &dest)
        } else {
            // For TCP server without destination, we don't know who to send to
            Err(std::io::Error::new(ErrorKind::InvalidInput, "TCP Server requires a destination address"))
        }
    }

    fn receive(&self, buffer: &mut [u8]) -> Result<(usize, SocketAddr)> {
        let mut server = self.server.lock().unwrap();
        
        // 1. Accept any waiting connections
        let _ = server.poll_accept();
        
        // 2. Read available data into per-connection buffers
        let clients = server.connected_clients();
        for addr in &clients {
            let mut tmp = [0u8; 4096];
            match server.raw_receive_from(&mut tmp, addr) {
                Ok(0) => { server.disconnect(addr); continue; }
                Ok(n) => { server.append_to_buffer(addr, &tmp[..n]); }
                Err(e) if e.kind() == ErrorKind::WouldBlock => {}
                Err(_) => { server.disconnect(addr); continue; }
            }
        }
        
        // 3. Check all buffers for a complete SOME/IP message
        for addr in &clients {
            if let Some(msg_len) = server.check_buffer(addr) {
                let copy_len = msg_len.min(buffer.len());
                server.drain_buffer(addr, copy_len, buffer);
                return Ok((copy_len, *addr));
            }
        }
        
        Err(std::io::Error::new(ErrorKind::WouldBlock, "No complete SOME/IP message available"))
    }

    fn local_addr(&self) -> Result<SocketAddr> {
        let server = self.server.lock().unwrap();
        server.local_addr()
    }

    fn set_nonblocking(&self, nonblocking: bool) -> Result<()> {
        let server = self.server.lock().unwrap();
        server.set_nonblocking(nonblocking)
    }
}

/// TCP server for accepting SOME/IP connections
pub struct TcpServer {
    listener: TcpListener,
    connections: HashMap<SocketAddr, TcpStream>,
    /// Per-connection receive buffers for SOME/IP message reassembly.
    tcp_buffers: HashMap<SocketAddr, Vec<u8>>,
}

impl TcpServer {
    /// Create a new TCP server bound to the given address
    pub fn bind(addr: SocketAddr) -> Result<Self> {
        let listener = TcpListener::bind(addr)?;
        Ok(TcpServer {
            listener,
            connections: HashMap::new(),
            tcp_buffers: HashMap::new(),
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
                self.tcp_buffers.entry(addr).or_insert_with(Vec::new);
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
    
    /// Receive data from a specific connected client.
    /// Returns a complete SOME/IP message if one is buffered, otherwise reads
    /// more data and returns WouldBlock until a full message is available.
    pub fn receive_from(&mut self, buffer: &mut [u8], addr: &SocketAddr) -> Result<usize> {
        // Read whatever is available
        if let Some(stream) = self.connections.get_mut(addr) {
            let mut tmp = [0u8; 4096];
            match stream.read(&mut tmp) {
                Ok(0) => {
                    self.tcp_buffers.remove(addr);
                    return Err(std::io::Error::new(ErrorKind::ConnectionReset, "EOF"));
                }
                Ok(n) => {
                    self.tcp_buffers.entry(*addr).or_insert_with(Vec::new).extend_from_slice(&tmp[..n]);
                }
                Err(e) if e.kind() == ErrorKind::WouldBlock => {}
                Err(e) => return Err(e),
            }
        } else {
            return Err(std::io::Error::new(ErrorKind::NotConnected, "Client not connected"));
        }

        // Check if buffer has a complete SOME/IP message
        if let Some(conn_buf) = self.tcp_buffers.get_mut(addr) {
            if let Some(msg_len) = someip_message_len(conn_buf) {
                let copy_len = msg_len.min(buffer.len());
                buffer[..copy_len].copy_from_slice(&conn_buf[..copy_len]);
                conn_buf.drain(..msg_len);
                return Ok(copy_len);
            }
        }
        Err(std::io::Error::new(ErrorKind::WouldBlock, "Incomplete SOME/IP message"))
    }

    /// Raw read from a connection (used by TcpServerTransport buffering layer).
    pub fn raw_receive_from(&mut self, buffer: &mut [u8], addr: &SocketAddr) -> Result<usize> {
        if let Some(stream) = self.connections.get_mut(addr) {
            stream.read(buffer)
        } else {
            Err(std::io::Error::new(ErrorKind::NotConnected, "Client not connected"))
        }
    }

    /// Append data to a connection's buffer.
    pub fn append_to_buffer(&mut self, addr: &SocketAddr, data: &[u8]) {
        self.tcp_buffers.entry(*addr).or_insert_with(Vec::new).extend_from_slice(data);
    }

    /// Check if a connection buffer has a complete SOME/IP message.
    pub fn check_buffer(&self, addr: &SocketAddr) -> Option<usize> {
        self.tcp_buffers.get(addr).and_then(|buf| someip_message_len(buf))
    }

    /// Drain bytes from a connection buffer into the output buffer.
    pub fn drain_buffer(&mut self, addr: &SocketAddr, len: usize, out: &mut [u8]) {
        if let Some(buf) = self.tcp_buffers.get_mut(addr) {
            let copy_len = len.min(out.len()).min(buf.len());
            out[..copy_len].copy_from_slice(&buf[..copy_len]);
            buf.drain(..len);
        }
    }
    
    /// Remove a connection and its buffer
    pub fn disconnect(&mut self, addr: &SocketAddr) {
        self.connections.remove(addr);
        self.tcp_buffers.remove(addr);
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    fn wrap_someip(payload: &[u8]) -> Vec<u8> {
        let mut msg = vec![0u8; 16];
        // SOME/IP Length = 8 (rest of header) + payload length
        let length = (8 + payload.len()) as u32;
        msg[4..8].copy_from_slice(&length.to_be_bytes());
        msg.extend_from_slice(payload);
        msg
    }
    
    #[test]
    fn test_tcp_server_creation() {
        let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let addr = server.local_addr().unwrap();
        assert!(addr.port() > 0);
    }
    
    #[test]
    fn test_tcp_server_initial_state() {
        let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        assert_eq!(server.connection_count(), 0);
        assert!(server.connected_clients().is_empty());
    }
    
    #[test]
    fn test_tcp_server_nonblocking() {
        let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        server.set_nonblocking(true).unwrap();
        // In nonblocking mode, accept should return None instead of blocking
    }
    
    #[test]
    fn test_tcp_client_server_communication() {
        // Start server
        let mut server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server_addr = server.local_addr().unwrap();
        
        // Connect client in background thread
        let client_thread = thread::spawn(move || {
            thread::sleep(Duration::from_millis(50));
            let client = TcpTransport::connect(server_addr).unwrap();
            
            // Send wrapped data
            let msg = wrap_someip(b"Hello Server");
            client.send(&msg, None).unwrap();
            
            // Receive response
            let mut buf = [0u8; 128];
            let (len, _) = client.receive(&mut buf).unwrap();
            // Buffer contains full SOME/IP message, payload starts at offset 16
            String::from_utf8_lossy(&buf[16..len]).to_string()
        });
        
        // Accept connection
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        loop {
            if std::time::Instant::now() > deadline {
                panic!("Timeout waiting for client connection");
            }
            match server.accept() {
                Ok(Some(addr)) => {
                    // Receive from client
                    let mut buf = [0u8; 128];
                    let mut len = 0;
                    // Need to wait for data to arrive and be processed by framing
                    let receive_deadline = std::time::Instant::now() + Duration::from_secs(2);
                    while std::time::Instant::now() < receive_deadline {
                        match server.receive_from(&mut buf, &addr) {
                            Ok(l) => { len = l; break; }
                            Err(e) if e.kind() == ErrorKind::WouldBlock => {
                                thread::sleep(Duration::from_millis(10));
                            }
                            Err(e) => panic!("Server receive error: {}", e),
                        }
                    }
                    if len == 0 {
                        panic!("Timeout waiting for data from client");
                    }
                    assert!(len >= 16);
                    assert_eq!(&buf[16..len], b"Hello Server");
                    
                    // Send response
                    let resp = wrap_someip(b"Hello Client");
                    server.send_to(&resp, &addr).unwrap();
                    break;
                }
                Ok(None) => thread::sleep(Duration::from_millis(10)),
                Err(_) => break,
            }
        }
        
        let response = client_thread.join().unwrap();
        assert_eq!(response, "Hello Client");
    }
    
    #[test]
    fn test_tcp_transport_local_addr() {
        let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server_addr = server.local_addr().unwrap();
        
        // Connect client
        let client = TcpTransport::connect(server_addr).unwrap();
        let local = client.local_addr().unwrap();
        assert!(local.port() > 0);
    }
    
    #[test]
    fn test_tcp_transport_peer_addr() {
        let server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server_addr = server.local_addr().unwrap();
        
        // Connect client
        let client = TcpTransport::connect(server_addr).unwrap();
        let peer = client.peer_addr().unwrap();
        assert_eq!(peer, server_addr);
    }
    
    #[test]
    fn test_server_disconnect() {
        let mut server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server_addr = server.local_addr().unwrap();
        
        // Connect client
        let _client = TcpTransport::connect(server_addr).unwrap();
        
        // Accept
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        loop {
            if std::time::Instant::now() > deadline {
                panic!("Timeout waiting for client connection");
            }
            if let Ok(Some(addr)) = server.accept() {
                assert_eq!(server.connection_count(), 1);
                server.disconnect(&addr);
                assert_eq!(server.connection_count(), 0);
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
    
    #[test]
    fn test_send_to_missing_client() {
        let mut server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let fake_addr: SocketAddr = "192.168.1.1:12345".parse().unwrap();
        
        let result = server.send_to(b"data", &fake_addr);
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().kind(), ErrorKind::NotConnected);
    }
    
    #[test]
    fn test_someip_message_roundtrip() {
        // Build a well-formed SOME/IP message: 16-byte header + 8-byte payload
        // Header: service_id=0x1001, method_id=0x0001, length=16 (8 hdr_rest + 8 payload),
        //         client_id=0x0001, session_id=0x0001, proto_ver=1, iface_ver=1,
        //         msg_type=0x00 (REQUEST), return_code=0x00
        let header: [u8; 16] = [
            0x10, 0x01, 0x00, 0x01, // service_id | method_id
            0x00, 0x00, 0x00, 0x10, // length (16 = 8 + 8 payload)
            0x00, 0x01, 0x00, 0x01, // client_id | session_id
            0x01, 0x01, 0x00, 0x00, // proto_ver | iface_ver | msg_type | return_code
        ];
        let payload: [u8; 8] = [0, 0, 0, 10, 0, 0, 0, 20]; // add(10, 20)
        
        let mut msg = Vec::new();
        msg.extend_from_slice(&header);
        msg.extend_from_slice(&payload);
        
        let mut server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server_addr = server.local_addr().unwrap();
        
        let client_thread = thread::spawn(move || {
            thread::sleep(Duration::from_millis(50));
            let client = TcpTransport::connect(server_addr).unwrap();
            client.send(&msg, None).unwrap();
            
            // Read response
            let mut buf = [0u8; 256];
            let (len, _) = client.receive(&mut buf).unwrap();
            buf[..len].to_vec()
        });
        
        // Server: accept, receive SOME/IP message, build response, send back
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        loop {
            if std::time::Instant::now() > deadline {
                panic!("Timeout waiting for client connection/data");
            }
            match server.accept() {
                Ok(Some(addr)) => {
                    let mut buf = [0u8; 256];
                    let mut len = 0;
                    let receive_deadline = std::time::Instant::now() + Duration::from_secs(2);
                    while std::time::Instant::now() < receive_deadline {
                        match server.receive_from(&mut buf, &addr) {
                            Ok(l) => { len = l; break; }
                            Err(e) if e.kind() == ErrorKind::WouldBlock => {
                                thread::sleep(Duration::from_millis(10));
                            }
                            Err(e) => panic!("Server receive error: {}", e),
                        }
                    }
                    
                    if len == 0 { panic!("Timeout waiting for data from client"); }
                    assert_eq!(len, 24); // 16 header + 8 payload
                    assert_eq!(&buf[0..4], &[0x10, 0x01, 0x00, 0x01]); // service_id | method_id
                    assert_eq!(buf[14], 0x00); // msg_type = REQUEST
                    
                    // Build response: same header but msg_type=0x80 (RESPONSE), payload = 30
                    let mut response = buf[..16].to_vec();
                    response[14] = 0x80; // RESPONSE
                    response[4..8].copy_from_slice(&[0x00, 0x00, 0x00, 0x0C]); // length = 12 (8 + 4)
                    response.extend_from_slice(&[0x00, 0x00, 0x00, 0x1E]); // result = 30
                    
                    server.send_to(&response, &addr).unwrap();
                    break;
                }
                Ok(None) => thread::sleep(Duration::from_millis(10)),
                Err(_) => break,
            }
        }
        
        let response = client_thread.join().unwrap();
        assert!(response.len() >= 20); // 16 header + 4 payload
        assert_eq!(response[14], 0x80); // msg_type = RESPONSE
        assert_eq!(&response[16..20], &[0x00, 0x00, 0x00, 0x1E]); // result = 30
    }
    
    #[test]
    fn test_tcp_server_multi_client() {
        let mut server = TcpServer::bind("127.0.0.1:0".parse().unwrap()).unwrap();
        let server_addr = server.local_addr().unwrap();
        
        // Spawn 3 clients
        let handles: Vec<_> = (0..3).map(|i| {
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(50));
                let client = TcpTransport::connect(server_addr).unwrap();
                let payload = format!("Client {}", i);
                let msg = wrap_someip(payload.as_bytes());
                client.send(&msg, None).unwrap();
                
                let mut buf = [0u8; 128];
                let (len, _) = client.receive(&mut buf).unwrap();
                String::from_utf8_lossy(&buf[16..len]).to_string()
            })
        }).collect();
        
        // Server: accept all 3, read from each, respond to each
        let mut accepted = Vec::new();
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        
        while accepted.len() < 3 && std::time::Instant::now() < deadline {
            if let Ok(Some(addr)) = server.accept() {
                accepted.push(addr);
            }
            thread::sleep(Duration::from_millis(10));
        }
        
        assert_eq!(accepted.len(), 3, "Expected 3 connections");
        assert_eq!(server.connection_count(), 3);
        
        // Read and respond to each client
        for addr in &accepted {
            let mut buf = [0u8; 128];
            let deadline = std::time::Instant::now() + Duration::from_secs(2);
            loop {
                match server.receive_from(&mut buf, addr) {
                    Ok(len) if len >= 16 => {
                        let msg = String::from_utf8_lossy(&buf[16..len]);
                        let response_payload = format!("Echo: {}", msg);
                        let response = wrap_someip(response_payload.as_bytes());
                        server.send_to(&response, addr).unwrap();
                        break;
                    }
                    _ => {
                        if std::time::Instant::now() >= deadline {
                            panic!("Timeout waiting for data from {:?}", addr);
                        }
                        thread::sleep(Duration::from_millis(10));
                    }
                }
            }
        }
        
        // Collect client results
        let results: Vec<String> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        for (i, r) in results.iter().enumerate() {
            assert_eq!(r, &format!("Echo: Client {}", i));
        }
        
        // Cleanup
        for addr in &accepted {
            server.disconnect(addr);
        }
        assert_eq!(server.connection_count(), 0);
    }
}
