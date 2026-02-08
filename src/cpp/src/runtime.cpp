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
    protocol = "udp";
    if (!config.providing.empty()) {
        const auto& first_svc = config.providing.begin()->second;
        if (!first_svc.endpoint.empty() && config.endpoints.count(first_svc.endpoint)) {
             const auto& ep = config.endpoints.at(first_svc.endpoint);
             port = ep.port;
             protocol = ep.protocol;
             for (char &c : protocol) c = std::tolower(c);
        }
    }

#ifdef _WIN32
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif

    int reuse = 1;

    // --- Transport Socket Initialization (UDP) ---
    sock = socket(AF_INET, SOCK_DGRAM, 0);
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
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

    sock_v6 = socket(AF_INET6, SOCK_DGRAM, 0);
    if (sock_v6 != INVALID_SOCKET) {
        int v6only = 1;
        setsockopt(sock_v6, IPPROTO_IPV6, IPV6_V6ONLY, (const char*)&v6only, sizeof(v6only));
        setsockopt(sock_v6, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
        sockaddr_in6 addr6 = {0};
        addr6.sin6_family = AF_INET6;
        addr6.sin6_addr = in6addr_any;
        addr6.sin6_port = htons(this->port);
        if (bind(sock_v6, (struct sockaddr*)&addr6, sizeof(addr6)) == SOCKET_ERROR) {
            this->logger->Log(LogLevel::WARN, "Runtime", "Failed to bind Transport IPv6 socket to " + std::to_string(this->port));
        }
    }

    // --- TCP Listener Initialization (if needed) ---
    if (protocol == "tcp") {
        tcp_listener = socket(AF_INET, SOCK_STREAM, 0);
        setsockopt(tcp_listener, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
        sockaddr_in t_addr = {0};
        t_addr.sin_family = AF_INET;
        t_addr.sin_addr.s_addr = htonl(INADDR_ANY);
        t_addr.sin_port = htons(this->port);
        if (bind(tcp_listener, (struct sockaddr*)&t_addr, sizeof(t_addr)) == SOCKET_ERROR) {
             this->logger->Log(LogLevel::WARN, "Runtime", "Failed to bind TCP listener (IPv4)");
        }
        listen(tcp_listener, 5);

        tcp_listener_v6 = socket(AF_INET6, SOCK_STREAM, 0);
        if (tcp_listener_v6 != INVALID_SOCKET) {
            int v6only = 1;
            setsockopt(tcp_listener_v6, IPPROTO_IPV6, IPV6_V6ONLY, (const char*)&v6only, sizeof(v6only));
            setsockopt(tcp_listener_v6, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
            sockaddr_in6 t_addr6 = {0};
            t_addr6.sin6_family = AF_INET6;
            t_addr6.sin6_addr = in6addr_any;
            t_addr6.sin6_port = htons(this->port);
            if (bind(tcp_listener_v6, (struct sockaddr*)&t_addr6, sizeof(t_addr6)) == SOCKET_ERROR) {
                this->logger->Log(LogLevel::WARN, "Runtime", "Failed to bind TCP listener (IPv6)");
            }
            listen(tcp_listener_v6, 5);
        }
        this->logger->Log(LogLevel::INFO, "Runtime", "TCP Listeners active on port " + std::to_string(this->port));
    }

    // --- Service Discovery Socket Initialization ---
    if (!config.sd_multicast_endpoint.empty() && config.endpoints.count(config.sd_multicast_endpoint)) {
        const auto& ep = config.endpoints.at(config.sd_multicast_endpoint);
        this->sd_multicast_port = ep.port;
        this->sd_multicast_ip = ep.ip;
    }
    
    sd_sock = socket(AF_INET, SOCK_DGRAM, 0);
    setsockopt(sd_sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
#ifdef SO_REUSEPORT
    setsockopt(sd_sock, SOL_SOCKET, SO_REUSEPORT, (const char*)&reuse, sizeof(reuse));
#endif
    sockaddr_in sd_addr = {0};
    sd_addr.sin_family = AF_INET;
    sd_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    sd_addr.sin_port = htons(this->sd_multicast_port);
    if (bind(sd_sock, (struct sockaddr*)&sd_addr, sizeof(sd_addr)) < 0) {
        this->logger->Log(LogLevel::ERR, "Runtime", "Failed to bind SD socket (IPv4) to port " + std::to_string(this->sd_multicast_port));
    }
    ip_mreq mreq;
    mreq.imr_multiaddr.s_addr = inet_addr(this->sd_multicast_ip.c_str());
    mreq.imr_interface.s_addr = inet_addr(config.ip.c_str());
    if (setsockopt(sd_sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, (const char*)&mreq, sizeof(mreq)) < 0) {
        mreq.imr_interface.s_addr = htonl(INADDR_ANY);
        setsockopt(sd_sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, (const char*)&mreq, sizeof(mreq));
    }
    in_addr if_addr;
    if_addr.s_addr = inet_addr(config.ip.c_str());
    setsockopt(sd_sock, IPPROTO_IP, IP_MULTICAST_IF, (const char*)&if_addr, sizeof(if_addr));
    int loop = 1;
    setsockopt(sd_sock, IPPROTO_IP, IP_MULTICAST_LOOP, (const char*)&loop, sizeof(loop));

    if (!config.sd_multicast_endpoint_v6.empty() && config.endpoints.count(config.sd_multicast_endpoint_v6)) {
        const auto& ep = config.endpoints.at(config.sd_multicast_endpoint_v6);
        this->sd_multicast_port_v6 = ep.port;
        this->sd_multicast_ip_v6 = ep.ip;
    }
    
    sd_sock_v6 = socket(AF_INET6, SOCK_DGRAM, 0);
    if (sd_sock_v6 != INVALID_SOCKET) {
        int v6only = 1;
        setsockopt(sd_sock_v6, IPPROTO_IPV6, IPV6_V6ONLY, (const char*)&v6only, sizeof(v6only));
        setsockopt(sd_sock_v6, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
#ifdef SO_REUSEPORT
        setsockopt(sd_sock_v6, SOL_SOCKET, SO_REUSEPORT, (const char*)&reuse, sizeof(reuse));
#endif
        sockaddr_in6 sd_addr6 = {0};
        sd_addr6.sin6_family = AF_INET6;
        sd_addr6.sin6_addr = in6addr_any;
        sd_addr6.sin6_port = htons(this->sd_multicast_port_v6);
        if (bind(sd_sock_v6, (struct sockaddr*)&sd_addr6, sizeof(sd_addr6)) < 0) {
            this->logger->Log(LogLevel::ERR, "Runtime", "Failed to bind SD socket (IPv6) to port " + std::to_string(this->sd_multicast_port_v6));
        }
        
        ipv6_mreq mreq6;
        inet_pton(AF_INET6, this->sd_multicast_ip_v6.c_str(), &mreq6.ipv6mr_multiaddr);
        mreq6.ipv6mr_interface = 0; // Default interface
        if (setsockopt(sd_sock_v6, IPPROTO_IPV6, IPV6_JOIN_GROUP, (const char*)&mreq6, sizeof(mreq6)) < 0) {
            this->logger->Log(LogLevel::WARN, "Runtime", "Failed to join IPv6 multicast group " + this->sd_multicast_ip_v6);
        }
        setsockopt(sd_sock_v6, IPPROTO_IPV6, IP_MULTICAST_LOOP, (const char*)&loop, sizeof(loop));
    }

    // --- Set Non-Blocking ---
#ifdef _WIN32
    unsigned long n_mode = 1;
    if (sd_sock != INVALID_SOCKET) ioctlsocket(sd_sock, FIONBIO, &n_mode);
    if (sd_sock_v6 != INVALID_SOCKET) ioctlsocket(sd_sock_v6, FIONBIO, &n_mode);
    if (sock != INVALID_SOCKET) ioctlsocket(sock, FIONBIO, &n_mode);
    if (sock_v6 != INVALID_SOCKET) ioctlsocket(sock_v6, FIONBIO, &n_mode);
    if (tcp_listener != INVALID_SOCKET) ioctlsocket(tcp_listener, FIONBIO, &n_mode);
    if (tcp_listener_v6 != INVALID_SOCKET) ioctlsocket(tcp_listener_v6, FIONBIO, &n_mode);
#else
    if (sd_sock != INVALID_SOCKET) fcntl(sd_sock, F_SETFL, O_NONBLOCK);
    if (sd_sock_v6 != INVALID_SOCKET) fcntl(sd_sock_v6, F_SETFL, O_NONBLOCK);
    if (sock != INVALID_SOCKET) fcntl(sock, F_SETFL, O_NONBLOCK);
    if (sock_v6 != INVALID_SOCKET) fcntl(sock_v6, F_SETFL, O_NONBLOCK);
    if (tcp_listener != INVALID_SOCKET) fcntl(tcp_listener, F_SETFL, O_NONBLOCK);
    if (tcp_listener_v6 != INVALID_SOCKET) fcntl(tcp_listener_v6, F_SETFL, O_NONBLOCK);
#endif

    this->logger->Log(LogLevel::INFO, "Runtime", "Initialized " + instance_name + " on port " + std::to_string(this->port) + " (" + protocol + ")");
    running = true;
    reactor_thread = std::jthread(&SomeIpRuntime::Run, this);
}

SomeIpRuntime::~SomeIpRuntime() {
    running = false;
    // jthread automatically joins on destruction
    closesocket(sock);
    closesocket(sd_sock);
#ifdef _WIN32
    WSACleanup();
#endif
}

void SomeIpRuntime::offer_service(const std::string& alias, RequestHandler* impl) {
    if (config.providing.count(alias)) {
        const auto& svc = config.providing.at(alias);
        services[svc.service_id] = impl;

        std::string ep_ip = "";
        std::string ep_ip6 = "";
        uint16_t svc_port = 0;
        std::string svc_proto = "udp";

        if (!svc.endpoint.empty() && config.endpoints.count(svc.endpoint)) {
            const auto& ep = config.endpoints.at(svc.endpoint);
            ep_ip = ep.ip;
            svc_port = ep.port;
            svc_proto = ep.protocol;
            if (ep.version == 6) ep_ip6 = ep.ip;
        }

        std::string mcast_ip = "";
        uint16_t mcast_port = 0;
        if (!svc.multicast.empty() && config.endpoints.count(svc.multicast)) {
            const auto& m_ep = config.endpoints.at(svc.multicast);
            mcast_ip = m_ep.ip;
            mcast_port = m_ep.port;
        }

        offered_services.push_back({svc.service_id, svc.instance_id, svc.major_version, svc.minor_version, svc_port, svc_proto, ep_ip, ep_ip6, mcast_ip, mcast_port});
        
        SendOffer(svc.service_id, svc.instance_id, svc.major_version, svc.minor_version, svc_port, svc_proto, ep_ip, ep_ip6, mcast_ip, mcast_port);
        this->logger->Log(LogLevel::INFO, "Runtime", "Offered Service '" + alias + "' (" + std::to_string(svc.service_id) + ") v" + std::to_string(svc.major_version) + "." + std::to_string(svc.minor_version) + " on port " + std::to_string(svc_port) + " (" + svc_proto + ")");
    }
}

bool SomeIpRuntime::wait_for_service(uint16_t service_id, uint16_t instance_id) {
    int timeout_ms = config.sd.request_timeout_ms;
    auto start = std::chrono::steady_clock::now();
    auto timeout = std::chrono::milliseconds(timeout_ms);
    while (std::chrono::steady_clock::now() - start < timeout) {
        {
            std::lock_guard<std::mutex> lock(remote_services_mutex);
            std::pair<uint16_t, uint16_t> key = {service_id, instance_id};
            
            bool found = false;
            sockaddr_storage addr;
            
            if (instance_id == 0xFFFF) {
                for (auto const& [k, v] : remote_services) {
                    if (k.first == service_id) {
                        found = true;
                        addr = v;
                        break;
                    }
                }
            } else if (remote_services.find(key) != remote_services.end()) {
                found = true;
                addr = remote_services[key];
            }

            if (found) {
                char ip_str[INET6_ADDRSTRLEN];
                uint16_t out_port = 0;
                if (addr.ss_family == AF_INET) {
                    inet_ntop(AF_INET, &((sockaddr_in*)&addr)->sin_addr, ip_str, INET_ADDRSTRLEN);
                    out_port = ntohs(((sockaddr_in*)&addr)->sin_port);
                } else {
                    inet_ntop(AF_INET6, &((sockaddr_in6*)&addr)->sin6_addr, ip_str, INET6_ADDRSTRLEN);
                    out_port = ntohs(((sockaddr_in6*)&addr)->sin6_port);
                }
                if (remote_services.find(key) == remote_services.end() || remote_services[key].ss_family != addr.ss_family) {
                    this->logger->Log(LogLevel::DEBUG, "Runtime", "Discovered service " + std::to_string(service_id) + " instance " + std::to_string(instance_id) + " at " + std::string(ip_str) + ":" + std::to_string(out_port));
                }
                return true;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return false;
}

void SomeIpRuntime::SendOffer(uint16_t service_id, uint16_t instance_id, uint8_t major, uint32_t minor, uint16_t port, const std::string& protocol, const std::string& endpoint_ip, const std::string& endpoint_ip_v6, const std::string& multicast_ip, uint16_t multicast_port) {
    auto build_sd = [&](bool ipv6) {
        std::vector<uint8_t> sd_payload;
        sd_payload.push_back(0x80); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00);
        
        // Count options
        int num_options = 1; // Unicast is always there
        bool has_mcast = !multicast_ip.empty();
        if (has_mcast) {
            if (ipv6 && multicast_ip.find(':') != std::string::npos) num_options++;
            else if (!ipv6 && multicast_ip.find('.') != std::string::npos) num_options++;
        }

        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(16);
        
        // Entry: Type=Offer(0x01), Index1=0, Index2=0, Options=num_options
        sd_payload.push_back(0x01); sd_payload.push_back(0x00); sd_payload.push_back(0x00); 
        sd_payload.push_back(num_options << 4);
        sd_payload.push_back((service_id >> 8) & 0xFF); sd_payload.push_back(service_id & 0xFF);
        sd_payload.push_back((instance_id >> 8) & 0xFF); sd_payload.push_back(instance_id & 0xFF);
        
        // Major Version + TTL (3 bytes)
        uint32_t maj_ttl = (uint32_t(major) << 24) | 0xFFFFFF;
        sd_payload.push_back((maj_ttl >> 24) & 0xFF);
        sd_payload.push_back((maj_ttl >> 16) & 0xFF);
        sd_payload.push_back((maj_ttl >> 8) & 0xFF);
        sd_payload.push_back(maj_ttl & 0xFF);
        
        // Minor Version (4 bytes)
        sd_payload.push_back((minor >> 24) & 0xFF);
        sd_payload.push_back((minor >> 16) & 0xFF);
        sd_payload.push_back((minor >> 8) & 0xFF);
        sd_payload.push_back(minor & 0xFF);
        
        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); 
        sd_payload.push_back(ipv6 ? 24 : 12); // Length of options
        
        uint8_t proto_id = (protocol == "tcp") ? 0x06 : 0x11;

        if (!ipv6) {
            sd_payload.push_back(0x00); sd_payload.push_back(0x09); sd_payload.push_back(0x04); sd_payload.push_back(0x00);
            std::string ip_str = endpoint_ip.empty() ? config.ip : endpoint_ip;
            uint32_t endpoint_ip_int = ntohl(inet_addr(ip_str.c_str()));
            sd_payload.push_back((endpoint_ip_int >> 24) & 0xFF);
            sd_payload.push_back((endpoint_ip_int >> 16) & 0xFF);
            sd_payload.push_back((endpoint_ip_int >> 8) & 0xFF);
            sd_payload.push_back(endpoint_ip_int & 0xFF);
            sd_payload.push_back(0x00); sd_payload.push_back(proto_id);
            sd_payload.push_back((port >> 8) & 0xFF); sd_payload.push_back(port & 0xFF);
        } else {
            sd_payload.push_back(0x00); sd_payload.push_back(0x15); sd_payload.push_back(0x06); sd_payload.push_back(0x00);
            sockaddr_in6 v6addr; 
            std::string ip6_str = endpoint_ip_v6.empty() ? config.ip_v6 : endpoint_ip_v6;
            inet_pton(AF_INET6, ip6_str.c_str(), &v6addr.sin6_addr);
            for(int i=0; i<16; ++i) sd_payload.push_back(v6addr.sin6_addr.s6_addr[i]);
            sd_payload.push_back(0x00); sd_payload.push_back(proto_id);
            sd_payload.push_back((port >> 8) & 0xFF); sd_payload.push_back(port & 0xFF);
        }

        if (has_mcast) {
            if (!ipv6 && multicast_ip.find('.') != std::string::npos) {
                  sd_payload.push_back(0x00); sd_payload.push_back(0x09); sd_payload.push_back(0x14); sd_payload.push_back(0x00);
                  uint32_t m_ip_int = ntohl(inet_addr(multicast_ip.c_str()));
                  sd_payload.push_back((m_ip_int >> 24) & 0xFF); sd_payload.push_back((m_ip_int >> 16) & 0xFF);
                  sd_payload.push_back((m_ip_int >> 8) & 0xFF); sd_payload.push_back(m_ip_int & 0xFF);
                  sd_payload.push_back(0x00); sd_payload.push_back(0x11); // UDP
                  uint16_t m_port = multicast_port ? multicast_port : port;
                  sd_payload.push_back((m_port >> 8) & 0xFF); sd_payload.push_back(m_port & 0xFF);
            } else if (ipv6 && multicast_ip.find(':') != std::string::npos) {
                  sd_payload.push_back(0x00); sd_payload.push_back(0x15); sd_payload.push_back(0x16); sd_payload.push_back(0x00);
                  sockaddr_in6 v6mcast; inet_pton(AF_INET6, multicast_ip.c_str(), &v6mcast.sin6_addr);
                  for(int i=0; i<16; ++i) sd_payload.push_back(v6mcast.sin6_addr.s6_addr[i]);
                  sd_payload.push_back(0x00); sd_payload.push_back(0x11); // UDP
                  uint16_t m_port = multicast_port ? multicast_port : port;
                  sd_payload.push_back((m_port >> 8) & 0xFF); sd_payload.push_back(m_port & 0xFF);
            }
        }

        uint32_t total_len = (uint32_t)sd_payload.size() + 8;
        std::vector<uint8_t> buffer;
        buffer.push_back(0xFF); buffer.push_back(0xFF); buffer.push_back(0x81); buffer.push_back(0x00);
        buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
        buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x01);
        buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00);
        buffer.insert(buffer.end(), sd_payload.begin(), sd_payload.end());
        return buffer;
    };

    if (sd_sock != INVALID_SOCKET) {
        std::vector<uint8_t> buffer = build_sd(false);
        sockaddr_in dest;
        dest.sin_family = AF_INET;
        dest.sin_addr.s_addr = inet_addr(this->sd_multicast_ip.c_str());
        dest.sin_port = htons(this->sd_multicast_port);
        sendto(sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    }
    if (sd_sock_v6 != INVALID_SOCKET) {
        std::vector<uint8_t> buffer = build_sd(true);
        sockaddr_in6 dest;
        dest.sin6_family = AF_INET6;
        inet_pton(AF_INET6, this->sd_multicast_ip_v6.c_str(), &dest.sin6_addr);
        dest.sin6_port = htons(this->sd_multicast_port_v6);
        sendto(sd_sock_v6, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    }
}

std::vector<uint8_t> SomeIpRuntime::SendRequest(uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload, sockaddr_storage target) {
    uint16_t session_id = 1; // Simplification for now
    uint32_t total_len = (uint32_t)payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(service_id >> 8); buffer.push_back(service_id & 0xFF);
    buffer.push_back(method_id >> 8); buffer.push_back(method_id & 0xFF); 
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(session_id >> 8); buffer.push_back(session_id & 0xFF);
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x00); buffer.push_back(0x00); 
    buffer.insert(buffer.end(), payload.begin(), payload.end());

    auto req = std::make_shared<PendingRequest>();
    {
        std::lock_guard<std::mutex> lock(pending_requests_mutex);
        pending_requests[{service_id, method_id, session_id}] = req;
    }

    std::string target_protocol = "udp";
    for(auto const& [name, req_cfg] : config.required) {
        if (req_cfg.service_id == service_id) {
            if (!req_cfg.endpoint.empty() && config.endpoints.count(req_cfg.endpoint)) {
                target_protocol = config.endpoints.at(req_cfg.endpoint).protocol;
            }
        }
    }
    for (char &c : target_protocol) c = std::tolower(c);

    if (target_protocol == "tcp") {
        SOCKET client_sock = socket(target.ss_family, SOCK_STREAM, 0);
        if (client_sock != INVALID_SOCKET) {
            int sl = (target.ss_family == AF_INET6) ? sizeof(sockaddr_in6) : sizeof(sockaddr_in);
            if (connect(client_sock, (struct sockaddr*)&target, sl) != SOCKET_ERROR) {
                send(client_sock, (const char*)buffer.data(), (int)buffer.size(), 0);
                char res_buf[4096];
                int res_bytes = recv(client_sock, res_buf, sizeof(res_buf), 0);
                closesocket(client_sock);
                std::lock_guard<std::mutex> lk(pending_requests_mutex);
                pending_requests.erase({service_id, method_id, session_id});
                if (res_bytes >= 16) {
                    return std::vector<uint8_t>(res_buf + 16, res_buf + res_bytes);
                }
            } else {
                closesocket(client_sock);
            }
        }
    } else {
        SOCKET s = (target.ss_family == AF_INET6) ? sock_v6 : sock;
        int sl = (target.ss_family == AF_INET6) ? sizeof(sockaddr_in6) : sizeof(sockaddr_in);
        if (s != INVALID_SOCKET && sendto(s, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&target, sl) != SOCKET_ERROR) {
            std::unique_lock<std::mutex> lock(req->mtx);
            if (req->cv.wait_for(lock, std::chrono::milliseconds(config.sd.request_timeout_ms), [&] { return req->completed; })) {
                std::lock_guard<std::mutex> lk(pending_requests_mutex);
                pending_requests.erase({service_id, method_id, session_id});
                return req->payload;
            }
        }
    }

    std::lock_guard<std::mutex> lk(pending_requests_mutex);
    pending_requests.erase({service_id, method_id, session_id});
    return {};
}

bool SomeIpRuntime::get_remote_service(uint16_t service_id, uint16_t instance_id, sockaddr_storage& out) {
    std::lock_guard<std::mutex> lock(remote_services_mutex);
    if (instance_id == 0xFFFF) {
        for (auto const& [k, v] : remote_services) {
            if (k.first == service_id) {
                out = v;
                return true;
            }
        }
    } else {
        std::pair<uint16_t, uint16_t> key = {service_id, instance_id};
        if (remote_services.find(key) != remote_services.end()) {
            out = remote_services[key];
            return true;
        }
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
    sd_payload.push_back(this->port >> 8); sd_payload.push_back(this->port & 0xFF); // Local port
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
    dest.sin_addr.s_addr = inet_addr(this->sd_multicast_ip.c_str());
    dest.sin_port = htons(this->sd_multicast_port);
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

void SomeIpRuntime::process_packet(const char* data, int len, sockaddr_storage src, SOCKET from_sock, bool is_tcp) {
    if (len < 16) return;
    uint16_t sid = (uint8_t(data[0]) << 8) | uint8_t(data[1]);
    uint16_t mid = (uint8_t(data[2]) << 8) | uint8_t(data[3]);
    uint32_t length = (uint8_t(data[4]) << 24) | (uint8_t(data[5]) << 16) | (uint8_t(data[6]) << 8) | uint8_t(data[7]);
    uint16_t cid = (uint8_t(data[8]) << 8) | uint8_t(data[9]);
    uint16_t ssid = (uint8_t(data[10]) << 8) | uint8_t(data[11]);
    uint8_t pv = data[12];
    uint8_t iv = data[13];
    uint8_t mt = data[14];

    if (mt == 0x00 || mt == 0x01) { // Request
        if (services.find(sid) != services.end()) {
            std::vector<uint8_t> payload(data + 16, data + len);
            auto res = services[sid]->handle({sid, mid, length, cid, ssid, pv, iv, mt, 0}, payload);
            if (!res.empty()) {
                uint32_t res_len = (uint32_t)res.size() + 8;
                std::vector<uint8_t> r_buf;
                r_buf.push_back(sid >> 8); r_buf.push_back(sid & 0xFF);
                r_buf.push_back(mid >> 8); r_buf.push_back(mid & 0xFF);
                r_buf.push_back(res_len >> 24); r_buf.push_back(res_len >> 16); r_buf.push_back(res_len >> 8); r_buf.push_back(res_len);
                r_buf.push_back(cid >> 8); r_buf.push_back(cid & 0xFF);
                r_buf.push_back(ssid >> 8); r_buf.push_back(ssid & 0xFF);
                r_buf.push_back(pv); r_buf.push_back(iv); r_buf.push_back(0x80); r_buf.push_back(0x00);
                r_buf.insert(r_buf.end(), res.begin(), res.end());
                if (is_tcp) send(from_sock, (const char*)r_buf.data(), (int)r_buf.size(), 0);
                else {
                    SOCKET s = (src.ss_family == AF_INET6) ? sock_v6 : sock;
                    int sl = (src.ss_family == AF_INET6) ? sizeof(sockaddr_in6) : sizeof(sockaddr_in);
                    sendto(s, (const char*)r_buf.data(), (int)r_buf.size(), 0, (struct sockaddr*)&src, sl);
                }
            }
        }
    } else if (mt == 0x80) { // Response
        std::lock_guard<std::mutex> lk(pending_requests_mutex);
        if (pending_requests.count({sid, mid, ssid})) {
            auto req = pending_requests[{sid, mid, ssid}];
            std::lock_guard<std::mutex> lk2(req->mtx);
            req->payload = std::vector<uint8_t>(data + 16, data + len);
            req->completed = true;
            req->cv.notify_one();
        }
    }
}

void SomeIpRuntime::process_sd_packet(const char* buf, int bytes, sockaddr_storage src) {
    if (bytes < 24) return;
    uint32_t len_entries = (uint8_t(buf[16+4]) << 24) | (uint8_t(buf[16+5]) << 16) | (uint8_t(buf[16+6]) << 8) | uint8_t(buf[16+7]);
    int offset = 16 + 8; 
    int end_entries = offset + len_entries;
    if (bytes < (int)(end_entries + 4)) return;

    while (offset + 16 <= end_entries) {
        uint8_t type = buf[offset];
        uint8_t index1 = buf[offset+1];
        uint16_t sid = (uint8_t(buf[offset+4]) << 8) | uint8_t(buf[offset+5]);
        uint16_t iid = (uint8_t(buf[offset+6]) << 8) | uint8_t(buf[offset+7]);
        uint32_t maj_ttl = (uint8_t(buf[offset+8]) << 24) | (uint8_t(buf[offset+9]) << 16) | (uint8_t(buf[offset+10]) << 8) | uint8_t(buf[offset+11]);
        uint32_t min = (uint8_t(buf[offset+12]) << 24) | (uint8_t(buf[offset+13]) << 16) | (uint8_t(buf[offset+14]) << 8) | uint8_t(buf[offset+15]);
        uint32_t ttl = maj_ttl & 0xFFFFFF;

        sockaddr_storage endpoint;
        memset(&endpoint, 0, sizeof(endpoint));
        bool has_endpoint = false;

        int options_start = end_entries + 4; 
        uint32_t len_opts = (uint8_t(buf[end_entries]) << 24) | (uint8_t(buf[end_entries+1]) << 16) | (uint8_t(buf[end_entries+2]) << 8) | uint8_t(buf[end_entries+3]);
        int opt_ptr = options_start;
        int opt_end = options_start + (int)len_opts;
        
        std::vector<sockaddr_storage> parsed_opts;
        while (opt_ptr + 3 <= opt_end) {
             uint16_t opt_len = (uint8_t(buf[opt_ptr]) << 8) | uint8_t(buf[opt_ptr+1]);
             uint8_t opt_type = buf[opt_ptr+2];
             sockaddr_storage opt_addr; memset(&opt_addr, 0, sizeof(opt_addr));
             
             if (opt_type == 0x04 && opt_len == 0x01 + 8) { // IPv4 Endpoint
                 sockaddr_in* sin = (sockaddr_in*)&opt_addr;
                 sin->sin_family = AF_INET;
                 memcpy(&sin->sin_addr, &buf[opt_ptr+4], 4);
                 uint16_t opt_port = (uint8_t(buf[opt_ptr+10]) << 8) | uint8_t(buf[opt_ptr+11]);
                 sin->sin_port = htons(opt_port);
             } else if (opt_type == 0x06 && opt_len == 0x01 + 20) { // IPv6 Endpoint
                 sockaddr_in6* sin6 = (sockaddr_in6*)&opt_addr;
                 sin6->sin6_family = AF_INET6;
                 memcpy(&sin6->sin6_addr, &buf[opt_ptr+4], 16);
                 uint16_t opt_port = (uint8_t(buf[opt_ptr+20]) << 8) | uint8_t(buf[opt_ptr+21]);
                 sin6->sin6_port = htons(opt_port);
             }
             parsed_opts.push_back(opt_addr);
             opt_ptr += 3 + opt_len;
        }

        if (index1 < parsed_opts.size()) {
            endpoint = parsed_opts[index1];
            if (endpoint.ss_family == AF_INET && ((sockaddr_in*)&endpoint)->sin_port != 0) has_endpoint = true;
            else if (endpoint.ss_family == AF_INET6 && ((sockaddr_in6*)&endpoint)->sin6_port != 0) has_endpoint = true;
        }

        if (type == 0x01) { // Offer
            if (has_endpoint && ttl > 0) {
                 bool changed = true;
                 {
                     std::lock_guard<std::mutex> lock(remote_services_mutex);
                     if (remote_services.count({sid, iid})) {
                         const auto& existing = remote_services[{sid, iid}];
                         if (existing.ss_family == endpoint.ss_family) {
                             if (existing.ss_family == AF_INET) {
                                  if (memcmp(&((sockaddr_in*)&existing)->sin_addr, &((sockaddr_in*)&endpoint)->sin_addr, 4) == 0 &&
                                      ((sockaddr_in*)&existing)->sin_port == ((sockaddr_in*)&endpoint)->sin_port) {
                                      changed = false;
                                  }
                             } else if (existing.ss_family == AF_INET6) {
                                  if (memcmp(&((sockaddr_in6*)&existing)->sin6_addr, &((sockaddr_in6*)&endpoint)->sin6_addr, 16) == 0 &&
                                      ((sockaddr_in6*)&existing)->sin6_port == ((sockaddr_in6*)&endpoint)->sin6_port) {
                                      changed = false;
                                  }
                             }
                         }
                     }
                     if (changed) remote_services[{sid, iid}] = endpoint;
                 }
                 if (changed) {
                     this->logger->Log(LogLevel::DEBUG, "SD", "Discovered Service " + std::to_string(sid) + ":" + std::to_string(iid));
                 }
            }
        } else if (type == 0x01 && ttl == 0) { // Stop Offer
             std::lock_guard<std::mutex> lock(remote_services_mutex);
             remote_services.erase({sid, iid});
        } else if (type == 0x06) { // Subscribe
            uint16_t eventgroup_id = (uint16_t)(maj_ttl & 0xFFFFFF) == 0 ? 0 : (uint16_t)(min >> 16); // In SOME/IP SD, EG is often in the minor field for Subscribe
            // Actually, SOME/IP SD Subscribe Eventgroup Entry has Eventgroup ID in the Reserved field of the entry.
            // Let's stick to the existing logic but make it IP-agnostic.
            eventgroup_id = (uint16_t)(min >> 16);
            std::pair<uint16_t, uint16_t> key = {sid, eventgroup_id};
            bool is_offered = false;
            uint16_t found_iid = 1;
            for(auto& off : offered_services) {
                if (off.service_id == sid) { is_offered = true; found_iid = off.instance_id; }
            }
            if (is_offered && has_endpoint) {
                if (ttl > 0) {
                    bool exists = false;
                    std::lock_guard<std::mutex> lock_sub(subscribers_mutex);
                    for(auto& sub : subscribers[key]) {
                        if (sub.ss_family == endpoint.ss_family) {
                            if (sub.ss_family == AF_INET) {
                                if (((sockaddr_in*)&sub)->sin_addr.s_addr == ((sockaddr_in*)&endpoint)->sin_addr.s_addr &&
                                    ((sockaddr_in*)&sub)->sin_port == ((sockaddr_in*)&endpoint)->sin_port) exists = true;
                            } else {
                                if (memcmp(&((sockaddr_in6*)&sub)->sin6_addr, &((sockaddr_in6*)&endpoint)->sin6_addr, 16) == 0 &&
                                    ((sockaddr_in6*)&sub)->sin6_port == ((sockaddr_in6*)&endpoint)->sin6_port) exists = true;
                            }
                        }
                    }
                    if (!exists) {
                        subscribers[key].push_back(endpoint);
                        this->logger->Log(LogLevel::INFO, "SD", "New Subscriber for "+std::to_string(sid)+" EG "+std::to_string(eventgroup_id));
                        
                        std::vector<uint8_t> ack_payload;
                        ack_payload.push_back(0x80); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00);
                        ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(16);
                        ack_payload.push_back(0x07); // Subscribe ACK
                        ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); 
                        ack_payload.push_back((sid >> 8) & 0xFF); ack_payload.push_back(sid & 0xFF);
                        ack_payload.push_back((found_iid >> 8) & 0xFF); ack_payload.push_back(found_iid & 0xFF);
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

                        if (src.ss_family == AF_INET) {
                            sockaddr_in dest;
                            dest.sin_family = AF_INET;
                            dest.sin_addr.s_addr = inet_addr(this->sd_multicast_ip.c_str());
                            dest.sin_port = htons(this->sd_multicast_port);
                            sendto(sd_sock, (const char*)abuf.data(), (int)abuf.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
                        } else {
                            sockaddr_in6 dest6;
                            dest6.sin6_family = AF_INET6;
                            inet_pton(AF_INET6, this->sd_multicast_ip_v6.c_str(), &dest6.sin6_addr);
                            dest6.sin6_port = htons(this->sd_multicast_port_v6);
                            sendto(sd_sock_v6, (const char*)abuf.data(), (int)abuf.size(), 0, (struct sockaddr*)&dest6, sizeof(dest6));
                        }
                    }
                }
            }
        } else if (type == 0x07) { // Subscribe ACK
            uint16_t eventgroup_id = (min >> 16);
            subscriptions[{sid, eventgroup_id}] = (ttl > 0);
        }
        offset += 16;
    }
}

void SomeIpRuntime::Run() {
    char buf[4096];
    last_offer_time = std::chrono::steady_clock::now();
    while (running) {
        auto now = std::chrono::steady_clock::now();
        uint64_t cycle_offer_ms = config.sd.cycle_offer_ms;
        if (cycle_offer_ms == 0) cycle_offer_ms = 1000;

        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_offer_time).count() > (long long)cycle_offer_ms) {
            last_offer_time = now;
            for (const auto& svc : offered_services) {
                SendOffer(svc.service_id, svc.instance_id, svc.major_version, svc.minor_version, svc.port, svc.protocol, svc.endpoint_ip, svc.endpoint_ip_v6, svc.multicast_ip, svc.multicast_port);
            }
        }
        fd_set readfds;
        FD_ZERO(&readfds);
        SOCKET max_fd = sd_sock;
        FD_SET(sd_sock, &readfds);
        if (sd_sock_v6 != INVALID_SOCKET) {
            FD_SET(sd_sock_v6, &readfds);
            if ((int)sd_sock_v6 > (int)max_fd) max_fd = sd_sock_v6;
        }
        if (sock != INVALID_SOCKET) {
            FD_SET(sock, &readfds);
            if ((int)sock > (int)max_fd) max_fd = sock;
        }
        if (sock_v6 != INVALID_SOCKET) {
            FD_SET(sock_v6, &readfds);
            if ((int)sock_v6 > (int)max_fd) max_fd = sock_v6;
        }
        if (tcp_listener != INVALID_SOCKET) {
            FD_SET(tcp_listener, &readfds);
            if ((int)tcp_listener > (int)max_fd) max_fd = tcp_listener;
        }
        if (tcp_listener_v6 != INVALID_SOCKET) {
            FD_SET(tcp_listener_v6, &readfds);
            if ((int)tcp_listener_v6 > (int)max_fd) max_fd = tcp_listener_v6;
        }
        
        {
            std::lock_guard<std::mutex> lock(tcp_clients_mutex);
            for (auto& client : tcp_clients) {
                FD_SET(client.first, &readfds);
                if ((int)client.first > (int)max_fd) max_fd = client.first;
            }
        }

        timeval timeout;
        timeout.tv_sec = 0;
        timeout.tv_usec = 100000;
        int activity = select((int)max_fd + 1, &readfds, NULL, NULL, &timeout);

        if (activity <= 0) continue;
        if (FD_ISSET(sd_sock, &readfds)) {
            sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
            int bytes = recvfrom(sd_sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
            if (bytes > 0) process_sd_packet(buf, bytes, src);
        }
        if (sd_sock_v6 != INVALID_SOCKET && FD_ISSET(sd_sock_v6, &readfds)) {
            sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
            int bytes = recvfrom(sd_sock_v6, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
            if (bytes > 0) process_sd_packet(buf, bytes, src);
        }

        if (sock != INVALID_SOCKET && FD_ISSET(sock, &readfds)) {
            sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
            int bytes = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
            if (bytes > 0) process_packet(buf, bytes, src, sock, false);
        }
        if (sock_v6 != INVALID_SOCKET && FD_ISSET(sock_v6, &readfds)) {
            sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
            int bytes = recvfrom(sock_v6, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
            if (bytes > 0) process_packet(buf, bytes, src, sock_v6, false);
        }

        if (tcp_listener != INVALID_SOCKET && FD_ISSET(tcp_listener, &readfds)) {
            sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
            SOCKET client = accept(tcp_listener, (struct sockaddr*)&src, &sl);
            if (client != INVALID_SOCKET) {
                std::lock_guard<std::mutex> lock(tcp_clients_mutex);
                tcp_clients.push_back({client, src});
            }
        }
        if (tcp_listener_v6 != INVALID_SOCKET && FD_ISSET(tcp_listener_v6, &readfds)) {
            sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
            SOCKET client = accept(tcp_listener_v6, (struct sockaddr*)&src, &sl);
            if (client != INVALID_SOCKET) {
                std::lock_guard<std::mutex> lock(tcp_clients_mutex);
                tcp_clients.push_back({client, src});
            }
        }

        std::lock_guard<std::mutex> lock(tcp_clients_mutex);
        for (auto it = tcp_clients.begin(); it != tcp_clients.end(); ) {
            if (FD_ISSET(it->first, &readfds)) {
                int bytes = recv(it->first, buf, sizeof(buf), 0);
                if (bytes <= 0) {
                    closesocket(it->first);
                    it = tcp_clients.erase(it);
                    continue;
                }
                process_packet(buf, bytes, it->second, it->first, true);
            }
            ++it;
        }
    }
}

void SomeIpRuntime::SendNotification(uint16_t service_id, uint16_t event_id, const std::vector<uint8_t>& payload) {
    uint16_t eventgroup_id = 1; // Simplified
    std::pair<uint16_t, uint16_t> key = {service_id, eventgroup_id};
    
    uint32_t total_len = (uint32_t)payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(service_id >> 8); buffer.push_back(service_id & 0xFF);
    buffer.push_back(event_id >> 8); buffer.push_back(event_id & 0xFF); 
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x00); buffer.push_back(0x01); // Session ID Placeholder
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00); // Notification
    buffer.insert(buffer.end(), payload.begin(), payload.end());

    std::lock_guard<std::mutex> lock(subscribers_mutex);
    if (subscribers.find(key) != subscribers.end()) {
        for (const auto& sub : subscribers[key]) {
            SOCKET s = (sub.ss_family == AF_INET6) ? sock_v6 : sock;
            int sl = (sub.ss_family == AF_INET6) ? sizeof(sockaddr_in6) : sizeof(sockaddr_in);
            if (s != INVALID_SOCKET) {
                sendto(s, (const char*)buffer.data(), (int)buffer.size(), 0, (const struct sockaddr*)&sub, sl);
            }
        }
    }
}

// Implementation of SendRequestGlue
std::vector<uint8_t> SendRequestGlue(void* rt_ptr, uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload) {
    SomeIpRuntime* rt = (SomeIpRuntime*)rt_ptr;
    if (!rt) return {};
    
    // Find target
    sockaddr_storage target;
    {
         int retries = 0;
         int max_retries = rt->config.sd.request_timeout_ms / 100;
         while (!rt->get_remote_service(service_id, 0xFFFF, target) && retries < max_retries) {
             std::this_thread::sleep_for(std::chrono::milliseconds(100));
             retries++;
         }
         if (retries >= max_retries) {
              // Try one last time or just fail
              if (!rt->get_remote_service(service_id, 0xFFFF, target)) {
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
    auto res = rt->SendRequest(service_id, method_id, payload, target);
    if (!res.empty()) return res;

    // Wait for response
    std::unique_lock<std::mutex> lock(req->mtx);
    if (req->cv.wait_for(lock, std::chrono::milliseconds(rt->config.sd.request_timeout_ms), [&]{ return req->completed; })) {
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
