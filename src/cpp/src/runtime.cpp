#include "fusion_hawking/runtime.hpp"
#include <iostream>

#ifdef _WIN32
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#define SOCKLEN_T int
#define closesocket closesocket
#else
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#define INVALID_SOCKET -1
#define SOCKET_ERROR -1
#define closesocket close
#define SOCKLEN_T socklen_t
#endif

namespace fusion_hawking {

SomeIpRuntime::SomeIpRuntime(const std::string& config_path, const std::string& instance_name, std::shared_ptr<ILogger> logger) {
    if (logger) this->logger = logger;
    else this->logger = std::make_shared<ConsoleLogger>();

    this->logger->Log(LogLevel::INFO, "Runtime", "Loading config from " + config_path);
    config = ConfigLoader::Load(config_path, instance_name);
    
    port = 0;
    if (!config.providing.empty()) port = config.providing.begin()->second.port;

#ifdef _WIN32
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);
    
    if (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
        addr.sin_port = 0;
        bind(sock, (struct sockaddr*)&addr, sizeof(addr));
    }
    int addrlen = sizeof(addr);
    getsockname(sock, (struct sockaddr*)&addr, (SOCKLEN_T*)&addrlen);
    this->port = ntohs(addr.sin_port);

    sd_sock = socket(AF_INET, SOCK_DGRAM, 0);
    int reuse = 1;
    setsockopt(sd_sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
    
    sockaddr_in sd_addr = {0};
    sd_addr.sin_family = AF_INET;
    sd_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    sd_addr.sin_port = htons(30490);
    bind(sd_sock, (struct sockaddr*)&sd_addr, sizeof(sd_addr));

    ip_mreq mreq;
    mreq.imr_multiaddr.s_addr = inet_addr("224.0.0.1");
    mreq.imr_interface.s_addr = htonl(INADDR_ANY);
    setsockopt(sd_sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, (const char*)&mreq, sizeof(mreq));

#ifdef _WIN32
    unsigned long mode = 1;
    ioctlsocket(sd_sock, FIONBIO, &mode);
    ioctlsocket(sock, FIONBIO, &mode);
#else
    fcntl(sd_sock, F_SETFL, O_NONBLOCK);
    fcntl(sock, F_SETFL, O_NONBLOCK);
#endif

    running = true;
    reactor_thread = std::thread(&SomeIpRuntime::Run, this);
}

SomeIpRuntime::~SomeIpRuntime() {
    running = false;
    if (reactor_thread.joinable()) reactor_thread.join();
    closesocket(sock);
    closesocket(sd_sock);
#ifdef _WIN32
    WSACleanup();
#endif
}

void SomeIpRuntime::offer_service(const std::string& alias, RequestHandler* impl) {
    uint16_t service_id = impl->get_service_id();
    uint16_t instance_id = 1;
    uint16_t svc_port = this->port;

    if (config.providing.find(alias) != config.providing.end()) {
        service_id = config.providing[alias].service_id;
        instance_id = config.providing[alias].instance_id;
        if (config.providing[alias].port != 0) svc_port = config.providing[alias].port;
    }

    services[service_id] = impl;
    offered_services.push_back(std::make_tuple(service_id, instance_id, svc_port));
    SendOffer(service_id, instance_id, svc_port);
    logger->Log(LogLevel::INFO, "Runtime", "Offered Service '" + alias + "' (0x" + std::to_string(service_id) + ") on port " + std::to_string(svc_port));
}

bool SomeIpRuntime::wait_for_service(uint16_t service_id, int timeout_ms) {
    auto start = std::chrono::steady_clock::now();
    auto timeout = std::chrono::milliseconds(timeout_ms);
    
    while (std::chrono::steady_clock::now() - start < timeout) {
        // Check if service is available
        {
            std::lock_guard<std::mutex> lock(remote_services_mutex);
            if (remote_services.find(service_id) != remote_services.end()) {
                sockaddr_in addr = remote_services[service_id];
                if (logger) {
                    char ip_str[INET_ADDRSTRLEN];
                    inet_ntop(AF_INET, &addr.sin_addr, ip_str, INET_ADDRSTRLEN);
                    logger->Log(LogLevel::INFO, "Runtime", "Discovered service 0x" + std::to_string(service_id) + " at " + std::string(ip_str) + ":" + std::to_string(ntohs(addr.sin_port)));
                }
                return true;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return false;
}

void SomeIpRuntime::SendOffer(uint16_t service_id, uint16_t instance_id, uint16_t port) {
    std::vector<uint8_t> sd_payload;
    sd_payload.push_back(0x80); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(16);
    sd_payload.push_back(0x01); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x01);
    sd_payload.push_back((service_id >> 8) & 0xFF); sd_payload.push_back(service_id & 0xFF);
    sd_payload.push_back((instance_id >> 8) & 0xFF); sd_payload.push_back(instance_id & 0xFF);
    sd_payload.push_back(0x01); sd_payload.push_back(0xFF); sd_payload.push_back(0xFF); sd_payload.push_back(0xFF);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(10);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x09);
    sd_payload.push_back(0x00); sd_payload.push_back(0x09); sd_payload.push_back(0x04); sd_payload.push_back(0x00);
    sd_payload.push_back(127); sd_payload.push_back(0); sd_payload.push_back(0); sd_payload.push_back(1);
    sd_payload.push_back(0x00); sd_payload.push_back(0x11);
    sd_payload.push_back((port >> 8) & 0xFF); sd_payload.push_back(port & 0xFF);

    uint32_t total_len = (uint32_t)sd_payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(0xFF); buffer.push_back(0xFF); buffer.push_back(0x81); buffer.push_back(0x00);
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x01);
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00);
    buffer.insert(buffer.end(), sd_payload.begin(), sd_payload.end());

    sockaddr_in dest;
    dest.sin_family = AF_INET;
    dest.sin_addr.s_addr = inet_addr("224.0.0.1");
    dest.sin_port = htons(30490);
    sendto(sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
}

void SomeIpRuntime::SendRequest(uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload, sockaddr_in target) {
    uint32_t total_len = (uint32_t)payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(service_id >> 8); buffer.push_back(service_id & 0xFF);
    buffer.push_back(method_id >> 8); buffer.push_back(method_id & 0xFF);
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x01);
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x00); buffer.push_back(0x00);
    buffer.insert(buffer.end(), payload.begin(), payload.end());
    sendto(sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&target, sizeof(target));
}

bool SomeIpRuntime::get_remote_service(uint16_t service_id, sockaddr_in& out) {
    std::lock_guard<std::mutex> lock(remote_services_mutex);
    if (remote_services.find(service_id) != remote_services.end()) {
        out = remote_services[service_id];
        return true;
    }
    return false;
}

void SomeIpRuntime::subscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id, uint32_t ttl) {
    // Build SubscribeEventgroup SD packet
    std::vector<uint8_t> sd_payload;
    sd_payload.push_back(0x80); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); // Flags
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(16);   // Entries Len
    
    // Entry: Type=0x06 (SubscribeEventgroup)
    sd_payload.push_back(0x06);  // Type
    sd_payload.push_back(0x00);  // Idx1
    sd_payload.push_back(0x00);  // Idx2
    sd_payload.push_back(0x10);  // NumOpts (1 << 4)
    sd_payload.push_back((service_id >> 8) & 0xFF); sd_payload.push_back(service_id & 0xFF);
    sd_payload.push_back((instance_id >> 8) & 0xFF); sd_payload.push_back(instance_id & 0xFF);
    
    // Maj/TTL
    uint32_t maj_ttl = (0x01 << 24) | (ttl & 0xFFFFFF);
    sd_payload.push_back((maj_ttl >> 24) & 0xFF);
    sd_payload.push_back((maj_ttl >> 16) & 0xFF);
    sd_payload.push_back((maj_ttl >> 8) & 0xFF);
    sd_payload.push_back(maj_ttl & 0xFF);
    
    // Minor = eventgroup_id << 16
    uint32_t minor = eventgroup_id << 16;
    sd_payload.push_back((minor >> 24) & 0xFF);
    sd_payload.push_back((minor >> 16) & 0xFF);
    sd_payload.push_back((minor >> 8) & 0xFF);
    sd_payload.push_back(minor & 0xFF);
    
    // Options Len (12 bytes for IPv4 endpoint)
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x0C);
    
    // IPv4 Endpoint Option
    sd_payload.push_back(0x00); sd_payload.push_back(0x09); // Len
    sd_payload.push_back(0x04); // Type = IPv4
    sd_payload.push_back(0x00); // Res
    sd_payload.push_back(127); sd_payload.push_back(0); sd_payload.push_back(0); sd_payload.push_back(1); // IP
    sd_payload.push_back(0x00); // Res
    sd_payload.push_back(0x11); // UDP
    sd_payload.push_back((port >> 8) & 0xFF); sd_payload.push_back(port & 0xFF);
    
    uint32_t total_len = (uint32_t)sd_payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(0xFF); buffer.push_back(0xFF); // Service ID 0xFFFF (SD)
    buffer.push_back(0x81); buffer.push_back(0x00); // Method ID 0x8100 (SD)
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x01);
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00);
    buffer.insert(buffer.end(), sd_payload.begin(), sd_payload.end());
    
    sockaddr_in dest = {0};
    dest.sin_family = AF_INET;
    dest.sin_addr.s_addr = inet_addr("224.0.0.1");
    dest.sin_port = htons(30490);
    sendto(sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    
    subscriptions[{service_id, eventgroup_id}] = false;
    if (logger) logger->Log(LogLevel::DEBUG, "SD", "Sent SubscribeEventgroup for " + std::to_string(service_id));
}

void SomeIpRuntime::unsubscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id) {
    subscribe_eventgroup(service_id, instance_id, eventgroup_id, 0);
    subscriptions.erase({service_id, eventgroup_id});
}

bool SomeIpRuntime::is_subscription_acked(uint16_t service_id, uint16_t eventgroup_id) {
    auto it = subscriptions.find({service_id, eventgroup_id});
    return it != subscriptions.end() && it->second;
}

void SomeIpRuntime::Run() {
    char buf[1500];
    last_offer_time = std::chrono::steady_clock::now();
    
    while (running) {
        // Periodic SD Offers (every 500ms)
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_offer_time).count() > 500) {
            last_offer_time = now;
            for (const auto& svc : offered_services) {
                SendOffer(std::get<0>(svc), std::get<1>(svc), std::get<2>(svc));
            }
        }
        
        sockaddr_in src;
        int len = sizeof(src);
        int bytes = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, (SOCKLEN_T*)&len);
        
        if (bytes >= 16) {
            std::vector<uint8_t> hdr_data(buf, buf+16);
            SomeIpHeader header = SomeIpHeader::deserialize(hdr_data);
            // Only handle Requests (0x00) or Requests No Return (0x01)
            if ((header.msg_type == 0x00 || header.msg_type == 0x01) && services.find(header.service_id) != services.end()) {
                std::vector<uint8_t> payload(buf + 16, buf + bytes);
                auto res_payload = services[header.service_id]->handle(header, payload);
                if (!res_payload.empty()) {
                    SomeIpHeader res_header = header;
                    res_header.length = (uint32_t)res_payload.size() + 8;
                    res_header.msg_type = 0x80;
                    auto hdr_bytes = res_header.serialize();
                    std::vector<uint8_t> msg = hdr_bytes;
                    msg.insert(msg.end(), res_payload.begin(), res_payload.end());
                    sendto(sock, (const char*)msg.data(), (int)msg.size(), 0, (struct sockaddr*)&src, sizeof(src));
                }
            }
        }
        
        bytes = recvfrom(sd_sock, buf, sizeof(buf), 0, NULL, NULL);
        if (bytes >= 56) {
             uint16_t service_id = (uint8_t(buf[28]) << 8) | uint8_t(buf[29]);
             uint32_t ip_val = (uint8_t(buf[48]) << 24) | (uint8_t(buf[49]) << 16) | (uint8_t(buf[50]) << 8) | uint8_t(buf[51]);
             uint16_t port_val = (uint8_t(buf[54]) << 8) | uint8_t(buf[55]);
             if (ip_val != 0 && port_val != 0) {
                 sockaddr_in remote = {0};
                 remote.sin_family = AF_INET;
                 remote.sin_addr.s_addr = htonl(ip_val);
                 remote.sin_port = htons(port_val);
                 {
                     std::lock_guard<std::mutex> lock(remote_services_mutex);
                     remote_services[service_id] = remote;
                 }
             }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}

void SendRequestGlue(void* rt_ptr, uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload) {
    SomeIpRuntime* rt = (SomeIpRuntime*)rt_ptr;
    sockaddr_in target;
    if (rt->get_remote_service(service_id, target)) {
        rt->SendRequest(service_id, method_id, payload, target);
    }
}

} // namespace fusion_hawking
