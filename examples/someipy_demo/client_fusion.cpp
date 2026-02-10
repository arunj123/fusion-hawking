#include <fusion_hawking/runtime.hpp>
#include <iostream>
#include <thread>
#include <chrono>

#ifdef _WIN32
#include <ws2tcpip.h>
#endif
#ifndef _WIN32
#include <arpa/inet.h>
#include <unistd.h>
#include <netinet/in.h>
#endif

using namespace fusion_hawking;

int main() {
    try {
        SomeIpRuntime runtime("client_config.json", "cpp_client");
        // runtime starts in constructor via jthread reactor

        std::cout << "[Fusion C++ Client] Waiting for Service 0x1234..." << std::endl;
        
        if (runtime.wait_for_service(0x1234, 0x0001)) {
            sockaddr_storage remote_ep;
            if (runtime.get_remote_service(0x1234, 0x0001, remote_ep)) {
                
                char ip_str[INET6_ADDRSTRLEN];
                uint16_t port = 0;
                if (remote_ep.ss_family == AF_INET) {
                    inet_ntop(AF_INET, &((sockaddr_in*)&remote_ep)->sin_addr, ip_str, INET_ADDRSTRLEN);
                    port = ntohs(((sockaddr_in*)&remote_ep)->sin_port);
                } else {
                    inet_ntop(AF_INET6, &((sockaddr_in6*)&remote_ep)->sin6_addr, ip_str, INET6_ADDRSTRLEN);
                    port = ntohs(((sockaddr_in6*)&remote_ep)->sin6_port);
                }

                std::cout << "[Fusion C++ Client] Discovered service at " << ip_str << ":" << port << std::endl;
                
                std::string msg = "Hello from Fusion C++!";
                std::vector<uint8_t> payload(msg.begin(), msg.end());
                
                auto response = runtime.SendRequest(0x1234, 0x0001, payload, remote_ep);
                
                if (!response.empty()) {
                    std::string res_str(response.begin(), response.end());
                    std::cout << "[Fusion C++ Client] Got Response: '" << res_str << "'" << std::endl;
                } else {
                    std::cout << "[Fusion C++ Client] RPC Timeout or Error" << std::endl;
                }
            }
        } else {
            std::cout << "[Fusion C++ Client] Service not found (Timeout)." << std::endl;
        }

        // Destructor handles stop
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
