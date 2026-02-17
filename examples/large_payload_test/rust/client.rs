use fusion_hawking::runtime::SomeIpRuntime;
use std::net::SocketAddr;
use std::time::Duration;

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let config_path = if args.len() > 1 { &args[1] } else { "examples/large_payload_test/config_rust.json" };
    
    println!("Starting Rust TP Client with config: {}", config_path);
    
    let runtime = SomeIpRuntime::load(config_path, "tp_client");
    
    // Run runtime in background thread
    let rt_clone = runtime.clone();
    std::thread::spawn(move || {
        rt_clone.run();
    });

    println!("Waiting for runtime initialization...");
    tokio::time::sleep(Duration::from_secs(2)).await;

    // Target defined in config_rust.json (server port 30500)
    let target: SocketAddr = "127.0.0.1:30500".parse().unwrap();
    let service_id = 0x5000;
    
    // 1. GET Request
    println!("Client: Sending GET Request (0x0001) to {}...", target);
    let payload = vec![];
    match runtime.send_request_and_wait(service_id, 0x0001, &payload, target).await {
        Some(response) => {
            println!("Client: Received Response size: {}", response.len());
            if response.len() == 5000 {
                println!("SUCCESS: Received 5000 bytes!");
                // Verify
                 let mut ok = true;
                for (i, byte) in response.iter().enumerate() {
                    if *byte != (i % 256) as u8 {
                        println!("ERROR: Mismatch at index {} expected {} got {}", i, i % 256, byte);
                        ok = false;
                        break;
                    }
                }
                if ok { println!("SUCCESS: Content Verified."); }
            } else {
                 println!("FAILURE: Expected 5000 bytes. Got {}", response.len());
            }
        },
        None => println!("FAILURE: Request Timed Out"),
    }

    // 2. ECHO Request
    println!("Client: Sending ECHO Request (0x0002) with 5000 bytes...");
    let mut large_payload = Vec::with_capacity(5000);
    for i in 0..5000 { large_payload.push((i % 256) as u8); }

    match runtime.send_request_and_wait(service_id, 0x0002, &large_payload, target).await {
        Some(response) => {
            println!("Client: Received ECHO Response size: {}", response.len());
             if response.len() == 5000 {
                // Verify
                 let mut ok = true;
                for (i, byte) in response.iter().enumerate() {
                    if *byte != (i % 256) as u8 {
                         println!("ERROR: ECHO Mismatch at index {} expected {} got {}", i, i % 256, byte);
                        ok = false;
                        break;
                    }
                }
                if ok { println!("SUCCESS: ECHO Content Verified."); }
            } else {
                 println!("FAILURE: Expected 5000 bytes ECHO. Got {}", response.len());
            }
        },
        None => println!("FAILURE: ECHO Request Timed Out"),
    }
    
    runtime.stop();
}
