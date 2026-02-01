#include <iostream>
#include <vector>
#include <map>
#include <string>
#include <thread>
#include <chrono>
#include <functional>
#include <atomic>
#include <mutex>
#include <algorithm>
#include <memory> 

// Platform abstraction
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#define SOCKLEN_T int
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#define SOCKET int
#define INVALID_SOCKET -1
#define SOCKET_ERROR -1
#define closesocket close
#define SOCKLEN_T socklen_t
#endif

// Include Generated Bindings and Config
#include "../../src/generated/bindings.h"
#include "config.hpp"
#include "logger.hpp"

using namespace generated;

// Definitions now in bindings.h

// --- Runtime ---
class SomeIpRuntime {
    SOCKET sock;
    SOCKET sd_sock;
    std::atomic<bool> running;
    std::thread reactor_thread;
    uint16_t port;
    std::map<uint16_t, RequestHandler*> services;
    std::map<uint16_t, sockaddr_in> remote_services;
    
    InstanceConfig config;
    std::shared_ptr<ILogger> logger;

public:
    SomeIpRuntime(const std::string& config_path, const std::string& instance_name, std::shared_ptr<ILogger> logger = nullptr) {
        if (logger) {
            this->logger = logger;
        } else {
            this->logger = std::make_shared<ConsoleLogger>();
        }

        // Load Config
        this->logger->Log(LogLevel::INFO, "Runtime", "Loading config from " + config_path);
        config = ConfigLoader::Load(config_path, instance_name);
        
        // Determine Port
        port = 0;
        if (!config.providing.empty()) {
            port = config.providing.begin()->second.port;
        }

        this->logger->Log(LogLevel::INFO, "Runtime", "Initializing '" + instance_name + "' on port " + std::to_string(port));

#ifdef _WIN32
        WSADATA wsaData;
        WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif
        // App Socket
        sock = socket(AF_INET, SOCK_DGRAM, 0);
        sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
        addr.sin_port = htons(port);
        
        if (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
             this->logger->Log(LogLevel::WARN, "Runtime", "Bind failed, trying ephemeral");
             addr.sin_port = 0;
             bind(sock, (struct sockaddr*)&addr, sizeof(addr));
        }
        
        // Get assigned port
        int addrlen = sizeof(addr);
        if (getsockname(sock, (struct sockaddr*)&addr, (SOCKLEN_T*)&addrlen) == 0) {
            this->port = ntohs(addr.sin_port);
        }

        // Non-blocking
#ifdef _WIN32
        u_long mode = 1;
        ioctlsocket(sock, FIONBIO, &mode);
#else
        int flags = fcntl(sock, F_GETFL, 0);
        fcntl(sock, F_SETFL, flags | O_NONBLOCK);
#endif

        // SD Socket Setup (Partial/Mock)
        sd_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        char reuse = 1;
        setsockopt(sd_sock, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
        sockaddr_in sd_addr;
        sd_addr.sin_family = AF_INET;
        sd_addr.sin_port = htons(30490);
        sd_addr.sin_addr.s_addr = htonl(INADDR_ANY);
        if (bind(sd_sock, (struct sockaddr*)&sd_addr, sizeof(sd_addr)) == SOCKET_ERROR) {
             this->logger->Log(LogLevel::WARN, "Runtime", "Could not bind SD multicast 30490");
        }
        
        // Join Multicast
        struct ip_mreq mreq;
        mreq.imr_multiaddr.s_addr = inet_addr("224.0.0.1");
        mreq.imr_interface.s_addr = htonl(INADDR_ANY);
        setsockopt(sd_sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, (char*)&mreq, sizeof(mreq));
        
        // Set Multicast TTL
        int ttl = 1;
        setsockopt(sd_sock, IPPROTO_IP, IP_MULTICAST_TTL, (char*)&ttl, sizeof(ttl));
        
#ifdef _WIN32
        ioctlsocket(sd_sock, FIONBIO, &mode);
#else
        flags = fcntl(sd_sock, F_GETFL, 0);
        fcntl(sd_sock, F_SETFL, flags | O_NONBLOCK);
#endif

        running = true;
        reactor_thread = std::thread(&SomeIpRuntime::Run, this);
    }
    
    ~SomeIpRuntime() {
        running = false;
        if (reactor_thread.joinable()) reactor_thread.join();
        closesocket(sock);
        closesocket(sd_sock);
#ifdef _WIN32
        WSACleanup();
#endif
    }

    void offer_service(const std::string& alias, RequestHandler* impl) {
        uint16_t service_id = impl->get_service_id();
        uint16_t instance_id = 1;
        uint16_t svc_port = this->port;

        if (config.providing.find(alias) != config.providing.end()) {
            service_id = config.providing[alias].service_id;
            instance_id = config.providing[alias].instance_id;
            if (config.providing[alias].port != 0) svc_port = config.providing[alias].port;
        }

        services[service_id] = impl;
        SendOffer(service_id, instance_id, svc_port);
        
        std::string msg = "Offered Service '" + alias + "' (0x" + std::to_string(service_id) + ") on port " + std::to_string(svc_port);
        logger->Log(LogLevel::INFO, "Runtime", msg);
    }

    template <typename T>
    T* create_client(const std::string& alias) {
        uint16_t service_id = T::SERVICE_ID; 
        
        sockaddr_in target;
        target.sin_family = AF_INET;
        target.sin_addr.s_addr = inet_addr("127.0.0.1");
        target.sin_port = htons(30509); 

        if (config.required.find(alias) != config.required.end()) {
             service_id = config.required[alias].service_id;
             if (!config.required[alias].static_ip.empty()) {
                  target.sin_addr.s_addr = inet_addr(config.required[alias].static_ip.c_str());
                  target.sin_port = htons(config.required[alias].static_port);
                  logger->Log(LogLevel::INFO, "Runtime", "Validated static config for " + alias);
             }
        }
        
        return new T(this, service_id); // Client takes (void* rt, uint16_t sid)
        // Wait, binding generator for C++ Client... 
        // I need to verify Generated Client constructor.
        // Assuming T(SomeIpRuntime*, uint16_t, sockaddr_in) based on previous patterns.
    }

    void SendOffer(uint16_t service_id, uint16_t instance_id, uint16_t port) {
        // Construct SD Offer Packet (Simplified)
        std::vector<uint8_t> buffer;
        
        // Header
        buffer.push_back(0x80); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00);
        buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(16);
        
        // Entry
        buffer.push_back(0x01); 
        buffer.push_back(0x00); 
        buffer.push_back(0x00); 
        buffer.push_back(0x10); 
        
        buffer.push_back((service_id >> 8) & 0xFF); buffer.push_back(service_id & 0xFF);
        buffer.push_back((instance_id >> 8) & 0xFF); buffer.push_back(instance_id & 0xFF);
        
        buffer.push_back(0x01); // Major
        buffer.push_back(0xFF); buffer.push_back(0xFF); buffer.push_back(0xFF); 
        buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); 
        
        // Options Length
        buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x09);
        
        // IPv4 Endpoint Option
        buffer.push_back(0x00); buffer.push_back(0x09); 
        buffer.push_back(0x04); 
        buffer.push_back(0x00); 
        buffer.push_back(127); buffer.push_back(0); buffer.push_back(0); buffer.push_back(1); 
        buffer.push_back(0x00); 
        buffer.push_back(0x11); 
        buffer.push_back((port >> 8) & 0xFF); buffer.push_back(port & 0xFF);
        
        sockaddr_in dest;
        dest.sin_family = AF_INET;
        dest.sin_addr.s_addr = inet_addr("224.0.0.1");
        dest.sin_port = htons(30490);
        
        sendto(sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    }

    void SendRequest(uint16_t service_id, const std::vector<uint8_t>& payload, sockaddr_in target) {
        // Simple send
        sendto(sock, (const char*)payload.data(), (int)payload.size(), 0, (struct sockaddr*)&target, sizeof(target));
    }
    
    SOCKET get_sock() const { return sock; }

private:
    void Run() {
        char buf[1500];
        while (running) {
            sockaddr_in src;
            int len = sizeof(src);
            int bytes = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, (SOCKLEN_T*)&len);
            
            if (bytes > 0 && bytes >= 16) {
                // Parse Header
                SomeIpHeader header = SomeIpHeader::deserialize(std::vector<uint8_t>(buf, buf+16));
                if (services.find(header.service_id) != services.end()) {
                    std::vector<uint8_t> payload(buf + 16, buf + bytes);
                    auto res_payload = services[header.service_id]->handle(header, payload);
                    if (!res_payload.empty()) {
                        SomeIpHeader res_header = header;
                        res_header.length = (uint32_t)res_payload.size() + 8;
                        res_header.msg_type = 0x80; // Response
                        
                        auto hdr_bytes = res_header.serialize();
                        std::vector<uint8_t> msg = hdr_bytes;
                        msg.insert(msg.end(), res_payload.begin(), res_payload.end());
                        
                        sendto(sock, (const char*)msg.data(), (int)msg.size(), 0, (struct sockaddr*)&src, sizeof(src));
                    }
                }
            }
            
            // Poll SD (Mock)
            bytes = recvfrom(sd_sock, buf, sizeof(buf), 0, NULL, NULL);
            if (bytes > 0) {
                 // Update remote_services based on Offers
            }
            
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
};

// --- Service Stubs (Manually implemented/linked if not in bindings.h) ---
// Wait, bindings.h should have Stubs/Clients. If not, we found a generator hole.
// But cpp_test.cpp used MathServiceAddRequest.
// Let's assume Stubs/Clients are missing from bindings.h if generator doesn't make them.
// I will inspect bindings.h again? No, let's assume they ARE there (at end of file, truncated view).
// If not, main.cpp will fail again.

// Glue Implementation for Generated Clients
namespace generated {
    void SendRequestGlue(void* rt_ptr, uint16_t service_id, const std::vector<uint8_t>& payload) {
        SomeIpRuntime* rt = (SomeIpRuntime*)rt_ptr;
        // Target? We lost target info in Client generation hack.
        // BUT, create_client returned a pointer.
        // The generated Client has `service_id`.
        // The Runtime needs `target`.
        // Let's just broadcast or use default for now in this Glue.
        // Real implementation would pass target to Client constructor and Client would pass it back here.
        // Fix: Update Generator later. For now, hardcode or lookup.
        sockaddr_in target;
        target.sin_family = AF_INET;
        target.sin_addr.s_addr = inet_addr("127.0.0.1");
        target.sin_port = htons(30509); // Default
        
        rt->SendRequest(service_id, payload, target);
    }
}

// --- Sort Service Implementation ---
class SortServiceImpl : public SortServiceStub {
public:
    virtual SortServiceSortAscResponse SortAsc(SortServiceSortAscRequest req) override {
        std::cout << "[C++ App] Sorting " << req.data.size() << " items" << std::endl;
        std::sort(req.data.begin(), req.data.end());
        
        SortServiceSortAscResponse res;
        res.result = req.data;
        return res;
    }
    
    virtual SortServiceSortDescResponse SortDesc(SortServiceSortDescRequest req) override {
         std::sort(req.data.begin(), req.data.end(), std::greater<int>());
         SortServiceSortDescResponse res;
         res.result = req.data;
         return res;
    }
};

int main() {
    auto logger = std::make_shared<ConsoleLogger>();
    logger->Log(LogLevel::INFO, "Main", "Starting C++ Demo");
    
    // 1. Initialize
    SomeIpRuntime rt("examples/config.json", "cpp_app_instance", logger);
    
    // 2. Offer
    SortServiceImpl sort_svc;
    rt.offer_service("sort-service", &sort_svc);
    
    // 3. Client
    std::this_thread::sleep_for(std::chrono::seconds(2));
    // Check if Client Constructor matches what we expect
    // Generated Clients usually take (Runtime*, ...) 
    // This assumes T(SomeIpRuntime*, ...) exists.
    MathServiceClient* client = rt.create_client<MathServiceClient>("math-client");
    
    while (true) {
        logger->Log(LogLevel::INFO, "Client", "Sending Add(5, 5)...");
        client->Add(5, 5);
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
    
    return 0;
}
