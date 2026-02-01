use fusion_hawking::{ServiceDiscovery, UdpTransport}; // Removed others
use std::net::{SocketAddr, Ipv4Addr};
use std::thread;
use std::time::Duration;

fn main() {
    println!("Starting SD Demo...");

    // 1. Provider
    let _provider_handle = thread::spawn(|| {
        let multicast_group: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        // Bind to a distinct port for sending (e.g., 50000) but we need to receive on 30490?
        // Multicast requires REUSEADDR. 
        // Our UdpTransport doesn't configure REUSEADDR by default?
        // If two processes/threads bind to 30490, we need SO_REUSEADDR.
        // For this demo, let's try binding to different ports and sending to multicast.
        // But SD receivers MUST listen on 30490.
        // If we can't bind multiple sockets to 30490, we can't run two peers on same machine unless we use proper multicast setup.
        // Let's assume Provider binds to 30490. Consumer binds to 30490?
        // This fails on Windows usually without SO_REUSEADDR.
        
        // Simulating:
        // Provider: Binds to 30490.
        // Consumer: Listens on 30490?
        
        // Let's check if UdpTransport supports this.
        // udp.rs: UdpSocket::bind(addr).
        // It does not set SO_REUSEADDR.
        
        // Workaround: Run Provider and Consumer sequentially in same process? No.
        // Or one binds to 30490, acts as listener.
        // In SOME/IP, everyone listens on 30490 for multicast.
        
        let bind_addr: SocketAddr = "0.0.0.0:0".parse().unwrap(); // Ephemeral for sending
        let transport = UdpTransport::new(bind_addr).unwrap();
        // Note: Sending FROM ephemeral is allowed.
        // But we won't receive multicast unless we join loopback? or specific interface.
        
        let mut sd = ServiceDiscovery::new(transport, multicast_group);
        
        println!("Provider offering Service 0x1234");
        sd.offer_service(0x1234, 1, 1, 0, 30501, 0x11); // TCP/UDP? 0x11 UDP
        
        loop {
            sd.poll();
            thread::sleep(Duration::from_millis(10));
        }
    });

    // 2. Consumer
    let consumer_handle = thread::spawn(|| {
        let multicast_group: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        
        // Consumer needs to LISTEN on Multicast Group.
        // Effectively bind "0.0.0.0:30490".
        // And Join Multicast Group.
        // UdpTransport logic:
        // bind("0.0.0.0:30490")
        // join_multicast_v4(224.0.0.1, 0.0.0.0)
        
        // Our current UdpTransport treats 'bind_addr' as bind.
        // It does NOT have join_multicast logic exposed.
        // We need to add join_multicast to UdpTransport?
        // Or assume the user does it?
        // UdpTransport is very basic.
        
        // Let's rely on standard UdpSocket via UdpTransport... but UdpTransport hides the socket.
        // I should have verified this "Integration with Transport" earlier!
        
        // Hack:
        // For this demo, Consumer runs on 30490.
        
        let bind_addr: SocketAddr = "0.0.0.0:30490".parse().unwrap();
        let transport = match UdpTransport::new(bind_addr) {
            Ok(t) => t,
            Err(e) => {
                println!("Consumer failed to bind 30490: {}", e);
                return;
            }
        };
        
        // Need to join multicast!
        if let std::net::IpAddr::V4(ref maddr) = multicast_group.ip() {
            // Interface 0.0.0.0 (any)
            let interface = Ipv4Addr::new(0, 0, 0, 0);
            transport.join_multicast_v4(maddr, &interface).expect("Failed to join multicast");
        }
        
        let mut sd = ServiceDiscovery::new(transport, multicast_group);
        
        loop {
            sd.poll();
            if let Some(service) = sd.find_service(0x1234, 1) {
                println!("Consumer FOUND Service 0x1234! Endpoint: {:?}", service.endpoint);
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
    });

    consumer_handle.join().unwrap();
    // provider runs forever
}
