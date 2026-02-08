#include "fusion_hawking/runtime.hpp"
#include <iostream>
#include <vector>

using namespace fusion_hawking;

class TCPMathService : public RequestHandler {
public:
    uint16_t get_service_id() override { return 0x1234; }
    uint32_t get_major_version() override { return 1; }
    uint32_t get_minor_version() override { return 0; }

    std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) override {
        std::cout << "[CPP Server] Received Request over TCP, method_id=" << header.method_id << std::endl;
        std::vector<uint8_t> response;
        if (header.method_id == 1) { // Add
             if (payload.size() >= 8) {
                 uint32_t a = (payload[0] << 24) | (payload[1] << 16) | (payload[2] << 8) | payload[3];
                 uint32_t b = (payload[4] << 24) | (payload[5] << 16) | (payload[6] << 8) | payload[7];
                 uint32_t res = a + b;
                 response.push_back(res >> 24); response.push_back(res >> 16); response.push_back(res >> 8); response.push_back(res & 0xFF);
             }
        }
        return response;
    }
};

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <config_path>" << std::endl;
        return 1;
    }
    
    auto logger = std::make_shared<ConsoleLogger>();
    SomeIpRuntime rt(argv[1], "tcp_server", logger);
    
    TCPMathService service;
    rt.offer_service("math-service", &service);
    
    std::cout << "[CPP Server] Running TCP Server..." << std::endl;
    while(true) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    return 0;
}
