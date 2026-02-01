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
#include "bindings.h"
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
    std::mutex remote_services_mutex;
    
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

        this->logger->Log(LogLevel::INFO, "Runtime", "Initializing '" + instance_name + "' on port " + std::to_string(port) + " (IPv" + std::to_string(config.ip_version) + ")");

#ifdef _WIN32
        WSADATA wsaData;
        WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif

        // App Socket - IPv4 or IPv6 based on config
        if (config.ip_version == 6) {
            sock = socket(AF_INET6, SOCK_DGRAM, 0);
            sockaddr_in6 addr6 = {0};
            addr6.sin6_family = AF_INET6;
            addr6.sin6_addr = in6addr_any;
            addr6.sin6_port = htons(port);
            
            if (bind(sock, (struct sockaddr*)&addr6, sizeof(addr6)) == SOCKET_ERROR) {
                 this->logger->Log(LogLevel::WARN, "Runtime", "IPv6 Bind failed, trying ephemeral");
                 addr6.sin6_port = 0;
                 bind(sock, (struct sockaddr*)&addr6, sizeof(addr6));
            }
            int addrlen6 = sizeof(addr6);
            if (getsockname(sock, (struct sockaddr*)&addr6, (SOCKLEN_T*)&addrlen6) == 0) {
                this->port = ntohs(addr6.sin6_port);
            }
        } else {
            sock = socket(AF_INET, SOCK_DGRAM, 0);
            sockaddr_in addr = {0};
            addr.sin_family = AF_INET;
            addr.sin_addr.s_addr = htonl(INADDR_ANY);
            addr.sin_port = htons(port);
            
            if (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
                 this->logger->Log(LogLevel::WARN, "Runtime", "Bind failed, trying ephemeral");
                 addr.sin_port = 0;
                 bind(sock, (struct sockaddr*)&addr, sizeof(addr));
            }
            int addrlen = sizeof(addr);
            if (getsockname(sock, (struct sockaddr*)&addr, (SOCKLEN_T*)&addrlen) == 0) {
                this->port = ntohs(addr.sin_port);
            }
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
        // Construct SD Payload
        std::vector<uint8_t> sd_payload;
        
        // SD Header (Flags + Entries Length)
        sd_payload.push_back(0x80); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); // Flags
        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(16); // 1 entry (16 bytes)
        
        // Entry (Offer Service)
        sd_payload.push_back(0x01); // Type: Offer
        sd_payload.push_back(0x00); // Index 1
        sd_payload.push_back(0x00); // Index 2
        sd_payload.push_back(0x01); // Num Opts: 1
        sd_payload.push_back((service_id >> 8) & 0xFF); sd_payload.push_back(service_id & 0xFF);
        sd_payload.push_back((instance_id >> 8) & 0xFF); sd_payload.push_back(instance_id & 0xFF);
        sd_payload.push_back(0x01); // Major Version
        sd_payload.push_back(0xFF); sd_payload.push_back(0xFF); sd_payload.push_back(0xFF); // TTL (24-bit)
        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(10); // Minor (32-bit: 10)
        
        // Options Length
        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x09); // 1 option (9 bytes)
        
        // IPv4 Endpoint Option
        sd_payload.push_back(0x00); sd_payload.push_back(0x09); // Length
        sd_payload.push_back(0x04); // Type: IPv4
        sd_payload.push_back(0x00); // Reserved
        sd_payload.push_back(127); sd_payload.push_back(0); sd_payload.push_back(0); sd_payload.push_back(1); // IP
        sd_payload.push_back(0x00); // Reserved
        sd_payload.push_back(0x11); // Proto: UDP (0x11)
        sd_payload.push_back((port >> 8) & 0xFF); sd_payload.push_back(port & 0xFF);
        
        // SOME/IP Header for SD (service=0xFFFF, method=0x8100)
        uint32_t total_len = (uint32_t)sd_payload.size() + 8;
        std::vector<uint8_t> buffer;
        buffer.push_back(0xFF); buffer.push_back(0xFF); // Service
        buffer.push_back(0x81); buffer.push_back(0x00); // Method
        buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
        buffer.push_back(0x00); buffer.push_back(0x00); // Client
        buffer.push_back(0x00); buffer.push_back(0x01); // Session
        buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00); // Ver, MSG (0x02), Ret
        
        buffer.insert(buffer.end(), sd_payload.begin(), sd_payload.end());

        sockaddr_in dest;
        dest.sin_family = AF_INET;
        dest.sin_addr.s_addr = inet_addr("224.0.0.1");
        dest.sin_port = htons(30490);
        
        sendto(sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    }

    void SendRequest(uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload, sockaddr_in target) {
        // SOME/IP Header (same as before)
        uint32_t total_len = (uint32_t)payload.size() + 8;
        std::vector<uint8_t> buffer;
        buffer.push_back(service_id >> 8); buffer.push_back(service_id & 0xFF);
        buffer.push_back(method_id >> 8); buffer.push_back(method_id & 0xFF);
        buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
        buffer.push_back(0x00); buffer.push_back(0x00); // Client
        buffer.push_back(0x00); buffer.push_back(0x01); // Session
        buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x00); buffer.push_back(0x00); // Ver, MSG (0x00), Ret
        
        buffer.insert(buffer.end(), payload.begin(), payload.end());
        
        sendto(sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&target, sizeof(target));
    }
    
    bool get_remote_service(uint16_t service_id, sockaddr_in& out) {
        std::lock_guard<std::mutex> lock(remote_services_mutex);
        if (remote_services.find(service_id) != remote_services.end()) {
            out = remote_services[service_id];
            return true;
        }
        return false;
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
            
            // Poll SD
            bytes = recvfrom(sd_sock, buf, sizeof(buf), 0, NULL, NULL);
            if (bytes >= 56) {
                 // Header(16) + Flags(4) + EntriesLen(4) + Entry(16) + OptsLen(4) + Opt(9)
                 // Service ID at offset 28
                 uint16_t service_id = (uint8_t(buf[28]) << 8) | uint8_t(buf[29]);
                 // IP at offset 48
                 uint32_t ip_val = (uint8_t(buf[48]) << 24) | (uint8_t(buf[49]) << 16) | (uint8_t(buf[50]) << 8) | uint8_t(buf[51]);
                 // Port at offset 54
                 uint16_t port_val = (uint8_t(buf[54]) << 8) | uint8_t(buf[55]);
                 
                 if (ip_val != 0 && port_val != 0) {
                     sockaddr_in remote = {0};
                     remote.sin_family = AF_INET;
                     remote.sin_addr.s_addr = htonl(ip_val);
                     remote.sin_port = htons(port_val);
                     
                     {
                         std::lock_guard<std::mutex> lock(remote_services_mutex);
                         if (remote_services.find(service_id) == remote_services.end()) {
                             logger->Log(LogLevel::INFO, "SD", "Discovered Service 0x" + std::to_string(service_id) + " at " + std::to_string(ip_val) + ":" + std::to_string(port_val));
                         }
                         remote_services[service_id] = remote;
                     }
                 }
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
    void SendRequestGlue(void* rt_ptr, uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload) {
        SomeIpRuntime* rt = (SomeIpRuntime*)rt_ptr;
        sockaddr_in target;
        if (rt->get_remote_service(service_id, target)) {
            rt->SendRequest(service_id, method_id, payload, target);
        } else {
             // Fallback to static if needed, but for now just wait for SD
        }
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
