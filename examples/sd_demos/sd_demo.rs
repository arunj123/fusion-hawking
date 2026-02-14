use fusion_hawking::sd::machine::{ServiceDiscovery, SdListener};
use fusion_hawking::transport::UdpTransport;
use std::net::{SocketAddr, Ipv4Addr, Ipv6Addr};
use std::thread;
use std::time::Duration;

fn main() {
    println!("Starting SD Demo...");

    // 1. Provider
    let _provider_handle = thread::spawn(|| {
        let transport_v4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let transport_v6 = UdpTransport::new("[::]:0".parse().unwrap()).unwrap();
        
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let local_ip_v6 = "::1".parse::<Ipv6Addr>().unwrap();
        let m_v4: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let m_v6: SocketAddr = "[FF02::4:C]:30490".parse().unwrap();
        
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: Some(transport_v4),
            transport_v6: Some(transport_v6),
            multicast_group_v4: Some(m_v4),
            multicast_group_v6: Some(m_v6),
            local_ip_v4: Some(local_ip),
            local_ip_v6: Some(local_ip_v6),
        });
        
        println!("Provider offering Service 0x1234");
        sd.offer_service(0x1234, 1, 1, 0, "primary", 30501, 0x11, None); 
        
        loop {
            sd.poll();
            thread::sleep(Duration::from_millis(10));
        }
    });

    // 2. Consumer
    let consumer_handle = thread::spawn(|| {
        let transport_v4 = UdpTransport::new("0.0.0.0:0".parse().unwrap()).unwrap();
        let transport_v6 = UdpTransport::new("[::]:0".parse().unwrap()).unwrap();
        
        let local_ip = Ipv4Addr::new(127, 0, 0, 1);
        let local_ip_v6 = "::1".parse::<Ipv6Addr>().unwrap();
        let m_v4: SocketAddr = "224.0.0.1:30490".parse().unwrap();
        let m_v6: SocketAddr = "[FF02::4:C]:30490".parse().unwrap();
        
        let mut sd = ServiceDiscovery::new();
        sd.add_listener(SdListener {
            alias: "primary".to_string(),
            transport_v4: Some(transport_v4),
            transport_v6: Some(transport_v6),
            multicast_group_v4: Some(m_v4),
            multicast_group_v6: Some(m_v6),
            local_ip_v4: Some(local_ip),
            local_ip_v6: Some(local_ip_v6),
        });
        
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
