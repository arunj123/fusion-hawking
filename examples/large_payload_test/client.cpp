#include <iostream>
#include <vector>
#include <thread>
#include <chrono>
#include <cassert>
#include <iomanip>

#include "fusion_hawking/runtime.hpp"

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#endif

using namespace fusion_hawking;

int main(int argc, char* argv[]) {
    // Basic Configuration
    std::string config_path = "config_client.json";
    if (argc > 1) config_path = argv[1];

    std::cout << "Client: Initializing Runtime with " << config_path << std::endl;
    SomeIpRuntime runtime(config_path, "client_instance");
    
    std::cout << "Waiting for service 0x5000..." << std::endl;
    
    if (!runtime.wait_for_service(0x5000, 1)) {
        std::cout << "FAILURE: Service 0x5000 not found!" << std::endl;
        return 1;
    }
    
    sockaddr_storage target = {0};
    if (!runtime.get_remote_service(0x5000, 1, target)) {
        std::cout << "FAILURE: Could not resolve service address!" << std::endl;
        return 1;
    }
    
    // Print resolved address
    char ip_str[INET6_ADDRSTRLEN];
    sockaddr_in* target_in = (sockaddr_in*)&target;
    inet_ntop(AF_INET, &target_in->sin_addr, ip_str, sizeof(ip_str));
    std::cout << "Resolved Service at " << ip_str << ":" << ntohs(target_in->sin_port) << std::endl;

    
    // 1. Test GET (Receive Large Payload)
    std::cout << "Client: Sending GET Request (0x0001) to 127.0.0.1:30500..." << std::endl;
    std::vector<uint8_t> payload = {}; // Empty payload for GET
    
    auto response = runtime.SendRequest(0x5000, 0x0001, payload, target);
    
    std::cout << "Client: Received Response size: " << response.size() << std::endl;
    
    if (response.size() == 5000) {
        std::cout << "SUCCESS: Received 5000 bytes!" << std::endl;
        // Verify content pattern 0x00..0xFF
        bool ok = true;
        for(size_t i=0; i<response.size(); ++i) {
            if (response[i] != (uint8_t)(i % 256)) {
                std::cout << "ERROR: Mismatch at index " << i << " expected " << (i%256) << " got " << (int)response[i] << std::endl;
                ok = false;
                break;
            }
        }
        if (ok) std::cout << "SUCCESS: Content Verified." << std::endl;
    } else {
        std::cout << "FAILURE: Expected 5000 bytes. Got " << response.size() << std::endl;
    }

    // 2. Test ECHO (Send Large Payload)
    std::cout << "Client: Sending ECHO Request (0x0002) with 5000 bytes..." << std::endl;
    std::vector<uint8_t> large_payload(5000);
    for(size_t i=0; i<large_payload.size(); ++i) large_payload[i] = (uint8_t)(i % 256);
    
    auto echo_response = runtime.SendRequest(0x5000, 0x0002, large_payload, target);
    
    std::cout << "Client: Received ECHO Response size: " << echo_response.size() << std::endl;
    if (echo_response.size() == 5000) {
        bool ok = true;
        for(size_t i=0; i<echo_response.size(); ++i) {
            if (echo_response[i] != (uint8_t)(i % 256)) {
                ok = false; break;
            }
        }
        if (ok) std::cout << "SUCCESS: ECHO Content Verified." << std::endl;
        else std::cout << "FAILURE: ECHO Content Mismatch." << std::endl;
    } else {
         std::cout << "FAILURE: Expected 5000 bytes ECHO. Got " << echo_response.size() << std::endl;
    }

    // Destructor handles shutdown
    return 0;
}
