use fusion_hawking::{ServiceDiscovery, UdpTransport}; // Removed others
use std::net::{SocketAddr, Ipv4Addr};
use std::thread;
use std::time::Duration;

fn main() {
    println!("Starting SD Demo...");

    // 1. Provider
    let _provider_handle = thread::spawn(|| {
        let _multicast_group: SocketAddr = "224.0.0.1:30490".parse().unwrap();
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
        
        let transport_v4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let transport_v6 = UdpTransport::new("[::]:0".parse().unwrap()).unwrap();
        
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let local_ip_v6 = "::1".parse().unwrap();
        let m_v4: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let m_v6: SocketAddr = "[FF02::4:C]:30490".parse().unwrap();
        let mut sd = ServiceDiscovery::new(transport_v4, transport_v6, local_ip, local_ip_v6, m_v4, m_v6);
        
        println!("Provider offering Service 0x1234");
        sd.offer_service(0x1234, 1, 1, 0, 30501, 0x11, None); // TCP/UDP? 0x11 UDP
        
        loop {
            sd.poll();
            thread::sleep(Duration::from_millis(10));
        }
    });

    // 2. Consumer
    let consumer_handle = thread::spawn(|| {
        let transport_v4 = UdpTransport::new_multicast("0.0.0.0:30490".parse().unwrap()).unwrap();
        let transport_v6 = UdpTransport::new_multicast("[::]:30490".parse().unwrap()).unwrap();
        
        // Join multicast!
        transport_v4.join_multicast_v4(&"224.0.0.1".parse().unwrap(), &Ipv4Addr::new(0,0,0,0)).expect("Failed to join v4 multicast");
        transport_v6.join_multicast_v6(&"FF02::4:C".parse().unwrap(), 0).expect("Failed to join v6 multicast");
        
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let local_ip_v6 = "::1".parse().unwrap();
        let m_v4: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let m_v6: SocketAddr = "[FF02::4:C]:30490".parse().unwrap();
        let mut sd = ServiceDiscovery::new(transport_v4, transport_v6, local_ip, local_ip_v6, m_v4, m_v6);
        
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
