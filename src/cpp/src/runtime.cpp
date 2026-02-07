#include "fusion_hawking/runtime.hpp"
#include <iostream>
#include <cstring>

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
#ifdef SO_REUSEPORT
    setsockopt(sd_sock, SOL_SOCKET, SO_REUSEPORT, (const char*)&reuse, sizeof(reuse));
#endif
    sockaddr_in sd_addr = {0};
    sd_addr.sin_family = AF_INET;
    sd_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    sd_addr.sin_port = htons(30490);
    if (bind(sd_sock, (struct sockaddr*)&sd_addr, sizeof(sd_addr)) < 0) {
        this->logger->Log(LogLevel::ERROR, "Runtime", "Failed to bind SD socket to port 30490");
        // Don't crash, but log error
    }
    ip_mreq mreq;
    mreq.imr_multiaddr.s_addr = inet_addr("224.0.0.1");
    mreq.imr_interface.s_addr = inet_addr(config.ip.c_str());
    setsockopt(sd_sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, (const char*)&mreq, sizeof(mreq));
    in_addr if_addr;
    if_addr.s_addr = inet_addr(config.ip.c_str());
    setsockopt(sd_sock, IPPROTO_IP, IP_MULTICAST_IF, (const char*)&if_addr, sizeof(if_addr));
    int loop = 1;
    setsockopt(sd_sock, IPPROTO_IP, IP_MULTICAST_LOOP, (const char*)&loop, sizeof(loop));
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
    this->logger->Log(LogLevel::INFO, "Runtime", "Offered Service '" + alias + "' (0x" + std::to_string(service_id) + ") on port " + std::to_string(svc_port));
}

bool SomeIpRuntime::wait_for_service(uint16_t service_id, int timeout_ms) {
    auto start = std::chrono::steady_clock::now();
    auto timeout = std::chrono::milliseconds(timeout_ms);
    while (std::chrono::steady_clock::now() - start < timeout) {
        {
            std::lock_guard<std::mutex> lock(remote_services_mutex);
            if (remote_services.find(service_id) != remote_services.end()) {
                sockaddr_in addr = remote_services[service_id];
                char ip_str[INET_ADDRSTRLEN];
                inet_ntop(AF_INET, &addr.sin_addr, ip_str, INET_ADDRSTRLEN);
                this->logger->Log(LogLevel::INFO, "Runtime", "Discovered service 0x" + std::to_string(service_id) + " at " + std::string(ip_str) + ":" + std::to_string(ntohs(addr.sin_port)));
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
    sd_payload.push_back(0x01); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x10);
    sd_payload.push_back((service_id >> 8) & 0xFF); sd_payload.push_back(service_id & 0xFF);
    sd_payload.push_back((instance_id >> 8) & 0xFF); sd_payload.push_back(instance_id & 0xFF);
    sd_payload.push_back(0x01); sd_payload.push_back(0xFF); sd_payload.push_back(0xFF); sd_payload.push_back(0xFF);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(10);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(12);
    sd_payload.push_back(0x00); sd_payload.push_back(0x09); sd_payload.push_back(0x04); sd_payload.push_back(0x00);
    uint32_t endpoint_ip = ntohl(inet_addr(config.ip.c_str()));
    sd_payload.push_back((endpoint_ip >> 24) & 0xFF);
    sd_payload.push_back((endpoint_ip >> 16) & 0xFF);
    sd_payload.push_back((endpoint_ip >> 8) & 0xFF);
    sd_payload.push_back(endpoint_ip & 0xFF);
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
    char ip[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &(target.sin_addr), ip, INET_ADDRSTRLEN);
    this->logger->Log(LogLevel::INFO, "Runtime", "Sending Req to " + std::string(ip) + ":" + std::to_string(ntohs(target.sin_port)));
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
    std::vector<uint8_t> sd_payload;
    sd_payload.push_back(0x80); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(16);
    sd_payload.push_back(0x06); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x10);
    sd_payload.push_back((service_id >> 8) & 0xFF); sd_payload.push_back(service_id & 0xFF);
    sd_payload.push_back((instance_id >> 8) & 0xFF); sd_payload.push_back(instance_id & 0xFF);
    uint32_t maj_ttl = (0x01 << 24) | (ttl & 0xFFFFFF);
    sd_payload.push_back((maj_ttl >> 24) & 0xFF); sd_payload.push_back((maj_ttl >> 16) & 0xFF); sd_payload.push_back((maj_ttl >> 8) & 0xFF); sd_payload.push_back(maj_ttl & 0xFF);
    uint32_t minor = eventgroup_id << 16;
    sd_payload.push_back((minor >> 24) & 0xFF); sd_payload.push_back((minor >> 16) & 0xFF); sd_payload.push_back((minor >> 8) & 0xFF); sd_payload.push_back(minor & 0xFF);
    sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(12);
    sd_payload.push_back(0x00); sd_payload.push_back(0x09); sd_payload.push_back(0x04); sd_payload.push_back(0x00);
    uint32_t local_ip = ntohl(inet_addr(config.ip.c_str()));
    sd_payload.push_back((local_ip >> 24) & 0xFF); sd_payload.push_back((local_ip >> 16) & 0xFF); sd_payload.push_back((local_ip >> 8) & 0xFF); sd_payload.push_back(local_ip & 0xFF);
    sd_payload.push_back(0x00); sd_payload.push_back(0x11);
    sd_payload.push_back((this->port >> 8) & 0xFF); sd_payload.push_back(this->port & 0xFF);
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
    subscriptions[{service_id, eventgroup_id}] = false;
    this->logger->Log(LogLevel::DEBUG, "SD", "Sent SubscribeEventgroup for " + std::to_string(service_id));
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
            } else if (header.msg_type == 0x80) {
                 // Handle Response
                 std::lock_guard<std::mutex> lock(pending_requests_mutex);
                 auto it = pending_requests.find({header.service_id, header.method_id, header.client_id});
                 // Client ID logic might need improvement if we use session ID matching strictly
                 // For now, let's assume unique Service/Method/Client tuple or just Service/Method if client is us (0)
                 // But wait, client_id is typically 0 for our client?
                 // Let's match purely on service/method and assuming we are the unique client for now or check session id?
                 // Simplification: Iterate pending requests to find match?
                 // Or just trust the tuple.
                 
                 // Better: Match by Service/Method/SessionID? Or just Service/Method since we are simple.
                 // Let's iterate values since we don't track session ID well yet.
                 for (auto& pair : pending_requests) {
                      if (std::get<0>(pair.first) == header.service_id && std::get<1>(pair.first) == header.method_id) {
                           // Found it
                           std::vector<uint8_t> payload(buf + 16, buf + bytes);
                           {
                               std::lock_guard<std::mutex> lk(pair.second->mtx);
                               pair.second->payload = payload;
                               pair.second->completed = true;
                           }
                           pair.second->cv.notify_one();
                           // Don't break, technically could be multiple if mismatch, but for this demo one is fine.
                           // Actually we should remove it? No, let the waiter remove it.
                      }
                 }
            }
        }
        bytes = recvfrom(sd_sock, buf, sizeof(buf), 0, NULL, NULL);
        if (bytes >= 24) { 
            uint32_t len_entries = (uint8_t(buf[16+4]) << 24) | (uint8_t(buf[16+5]) << 16) | (uint8_t(buf[16+6]) << 8) | uint8_t(buf[16+7]);
            int offset = 16 + 8; 
            int end_entries = offset + len_entries;
            if (bytes >= end_entries + 4) { 
                while (offset + 16 <= end_entries) {
                    uint8_t type = buf[offset];
                    uint8_t index1 = buf[offset+1];
                    uint16_t sid = (uint8_t(buf[offset+4]) << 8) | uint8_t(buf[offset+5]);
                    uint16_t iid = (uint8_t(buf[offset+6]) << 8) | uint8_t(buf[offset+7]);
                    uint32_t maj_ttl = (uint8_t(buf[offset+8]) << 24) | (uint8_t(buf[offset+9]) << 16) | (uint8_t(buf[offset+10]) << 8) | uint8_t(buf[offset+11]);
                    uint32_t min = (uint8_t(buf[offset+12]) << 24) | (uint8_t(buf[offset+13]) << 16) | (uint8_t(buf[offset+14]) << 8) | uint8_t(buf[offset+15]);
                    uint32_t ttl = maj_ttl & 0xFFFFFF;
                    sockaddr_in endpoint = {0};
                    bool has_endpoint = false;
                    int options_start = end_entries + 4; 
                    uint32_t len_opts = (uint8_t(buf[end_entries]) << 24) | (uint8_t(buf[end_entries+1]) << 16) | (uint8_t(buf[end_entries+2]) << 8) | uint8_t(buf[end_entries+3]);
                    int opt_ptr = options_start;
                    int opt_end = options_start + len_opts;
                    std::vector<sockaddr_in> parsed_opts;
                    while (opt_ptr + 3 <= opt_end) {
                         uint16_t opt_len = (uint8_t(buf[opt_ptr]) << 8) | uint8_t(buf[opt_ptr+1]);
                         uint8_t opt_type = buf[opt_ptr+2];
                         sockaddr_in opt_addr = {0};
                         if (opt_type == 0x04 && opt_len == 0x09) { 
                             opt_addr.sin_family = AF_INET;
                             memcpy(&opt_addr.sin_addr.s_addr, &buf[opt_ptr+4], 4);
                             uint16_t opt_port = (uint8_t(buf[opt_ptr+10]) << 8) | uint8_t(buf[opt_ptr+11]);
                             opt_addr.sin_port = htons(opt_port);
                         }
                         parsed_opts.push_back(opt_addr);
                         opt_ptr += 3 + opt_len;
                    }
                    if (index1 < parsed_opts.size()) {
                        endpoint = parsed_opts[index1];
                        if (endpoint.sin_port != 0) has_endpoint = true;
                    }
                    if (type == 0x01) { 
                        if (has_endpoint && ttl > 0) {
                             this->logger->Log(LogLevel::DEBUG, "SD", "Discovered Service 0x" + std::to_string(sid));
                             std::lock_guard<std::mutex> lock(remote_services_mutex);
                             remote_services[sid] = endpoint;
                        }
                    } else if (type == 0x06) { 
                        uint16_t eventgroup_id = (min >> 16);
                        std::pair<uint16_t, uint16_t> key = {sid, eventgroup_id};
                        bool is_offered = false;
                        for(auto& off : offered_services) {
                            if (std::get<0>(off) == sid) is_offered = true;
                        }
                        if (is_offered && has_endpoint) {
                            if (ttl > 0) {
                                bool exists = false;
                                for(auto& sub : subscribers[key]) {
                                    if (sub.sin_addr.s_addr == endpoint.sin_addr.s_addr && sub.sin_port == endpoint.sin_port) exists = true;
                                }
                                if (!exists) {
                                    subscribers[key].push_back(endpoint);
                                    this->logger->Log(LogLevel::INFO, "SD", "New Subscriber for 0x"+std::to_string(sid)+" EG "+std::to_string(eventgroup_id));
                                    std::vector<uint8_t> ack_payload;
                                    ack_payload.push_back(0x80); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00);
                                    ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(16);
                                    ack_payload.push_back(0x07); 
                                    ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); 
                                    ack_payload.push_back((sid >> 8) & 0xFF); ack_payload.push_back(sid & 0xFF);
                                    ack_payload.push_back((iid >> 8) & 0xFF); ack_payload.push_back(iid & 0xFF);
                                    ack_payload.push_back((maj_ttl >> 24) & 0xFF); ack_payload.push_back((maj_ttl >> 16) & 0xFF); ack_payload.push_back((maj_ttl >> 8) & 0xFF); ack_payload.push_back(maj_ttl & 0xFF);
                                    ack_payload.push_back((min >> 24) & 0xFF); ack_payload.push_back((min >> 16) & 0xFF); ack_payload.push_back((min >> 8) & 0xFF); ack_payload.push_back(min & 0xFF);
                                    ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); 
                                    uint32_t total_len = (uint32_t)ack_payload.size() + 8;
                                    std::vector<uint8_t> abuf;
                                    abuf.push_back(0xFF); abuf.push_back(0xFF); abuf.push_back(0x81); abuf.push_back(0x00);
                                    abuf.push_back(total_len >> 24); abuf.push_back(total_len >> 16); abuf.push_back(total_len >> 8); abuf.push_back(total_len);
                                    abuf.push_back(0x00); abuf.push_back(0x00); abuf.push_back(0x00); abuf.push_back(0x01);
                                    abuf.push_back(0x01); abuf.push_back(0x01); abuf.push_back(0x02); abuf.push_back(0x00);
                                    abuf.insert(abuf.end(), ack_payload.begin(), ack_payload.end());
                                    sockaddr_in dest = {0};
                                    dest.sin_family = AF_INET;
                                    dest.sin_addr.s_addr = inet_addr("224.0.0.1");
                                    dest.sin_port = htons(30490);
                                    sendto(sd_sock, (const char*)abuf.data(), (int)abuf.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
                                }
                            }
                        }
                    } else if (type == 0x07) { 
                         uint16_t eventgroup_id = (min >> 16);
                         subscriptions[{sid, eventgroup_id}] = (ttl > 0);
                    }
                    offset += 16;
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}

void SomeIpRuntime::SendNotification(uint16_t service_id, uint16_t event_id, const std::vector<uint8_t>& payload) {
    uint16_t eventgroup_id = 1;
    std::pair<uint16_t, uint16_t> key = {service_id, eventgroup_id};
    if (subscribers.find(key) == subscribers.end()) return;
    uint32_t total_len = (uint32_t)payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(service_id >> 8); buffer.push_back(service_id & 0xFF);
    buffer.push_back(event_id >> 8); buffer.push_back(event_id & 0xFF); 
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x01);
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x02); 
    buffer.insert(buffer.end(), payload.begin(), payload.end());
    for (const auto& sub : subscribers[key]) {
        sendto(sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&sub, sizeof(sub));
    }
}

// Implementation of SendRequestGlue
std::vector<uint8_t> SendRequestGlue(void* rt_ptr, uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload) {
    SomeIpRuntime* rt = (SomeIpRuntime*)rt_ptr;
    if (!rt) return {};
    
    // Find target
    sockaddr_in target;
    {
         int retries = 0;
         while (!rt->get_remote_service(service_id, target) && retries < 5) {
             std::this_thread::sleep_for(std::chrono::milliseconds(100));
             retries++;
         }
         if (retries >= 5) {
              // Try one last time or just fail
              if (!rt->get_remote_service(service_id, target)) {
                  if(rt->logger) rt->logger->Log(LogLevel::WARN, "Glue", "Service not found 0x" + std::to_string(service_id));
                  return {};
              }
         }
    }

    auto req = std::make_shared<SomeIpRuntime::PendingRequest>();
    
    {
        std::lock_guard<std::mutex> lock(rt->pending_requests_mutex);
        // Using 0 as client ID for simple matching
        rt->pending_requests[{service_id, method_id, 0}] = req;
    }

    if(rt->logger) rt->logger->Log(LogLevel::DEBUG, "Glue", "Sending Request...");
    rt->SendRequest(service_id, method_id, payload, target);

    // Wait for response
    std::unique_lock<std::mutex> lock(req->mtx);
    if (req->cv.wait_for(lock, std::chrono::seconds(2), [&]{ return req->completed; })) {
         // Completed
         // if(rt->logger) rt->logger->Log(LogLevel::DEBUG, "Glue", "Got Response!");
         std::lock_guard<std::mutex> map_lock(rt->pending_requests_mutex);
         rt->pending_requests.erase({service_id, method_id, 0});
         return req->payload;
    } else {
         // Timeout
         std::lock_guard<std::mutex> map_lock(rt->pending_requests_mutex);
         rt->pending_requests.erase({service_id, method_id, 0});
         if (rt->logger) rt->logger->Log(LogLevel::WARN, "Glue", "Timeout waiting for response to " + std::to_string(service_id) + ":" + std::to_string(method_id));
         return {};
    }
}


} // namespace fusion_hawking
