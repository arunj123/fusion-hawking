#include "fusion_hawking/runtime.hpp"
#include <iostream>
#include <cstring>

#ifdef _WIN32
#include <ws2tcpip.h>
#include <iphlpapi.h>
#include <netioapi.h>
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "iphlpapi.lib")
#define SOCKLEN_T int
#define closesocket closesocket
#define GET_SOCKET_ERROR() WSAGetLastError()
#else
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <net/if.h>
#include <errno.h>
#define closesocket close
#define SOCKLEN_T socklen_t
#define GET_SOCKET_ERROR() errno
#endif

namespace fusion_hawking {

// Thread-safe session ID manager instance
static SessionIdManager g_session_mgr;
static std::mutex g_session_mgr_mutex;

static uint16_t next_session(uint16_t service_id, uint16_t method_id) {
    std::lock_guard<std::mutex> lock(g_session_mgr_mutex);
    return g_session_mgr.next_session_id(service_id, method_id);
}

// Helper for Windows Interface Resolution
static unsigned int ResolveInterfaceIndex(const std::string& name) {
    // Try standard name to index first
    unsigned int idx = if_nametoindex(name.c_str());
    if (idx != 0) return idx;

#ifdef _WIN32
    // Try friendly name resolution using GetAdaptersAddresses
    ULONG outBufLen = 15000;
    PIP_ADAPTER_ADDRESSES pAddresses = (PIP_ADAPTER_ADDRESSES)malloc(outBufLen);
    if (pAddresses == NULL) return 0;

    ULONG ret = GetAdaptersAddresses(AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX, NULL, pAddresses, &outBufLen);
    if (ret == ERROR_BUFFER_OVERFLOW) {
        free(pAddresses);
        pAddresses = (PIP_ADAPTER_ADDRESSES)malloc(outBufLen);
        if (pAddresses == NULL) return 0;
        ret = GetAdaptersAddresses(AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX, NULL, pAddresses, &outBufLen);
    }

    if (ret == NO_ERROR) {
        PIP_ADAPTER_ADDRESSES pCurrAddresses = pAddresses;
        while (pCurrAddresses) {
            if (pCurrAddresses->FriendlyName) {
                // Convert FriendlyName (PWCHAR) to something comparable
                // Simple ASCII->Wide conversion for target name since "Wi-Fi" is ASCII
                std::wstring friendlyName(pCurrAddresses->FriendlyName);
                std::wstring targetName(name.begin(), name.end()); 
                
                // Case-insensitive comparison could be better but exact match usually fine for "Wi-Fi"
                if (friendlyName == targetName) {
                     // Return Ipv6IfIndex if we are likely in IPv6 context context
                     // But if_nametoindex returns the generic one. 
                     // We'll prefer Ipv6IfIndex if available and non-zero, else IfIndex
                     idx = pCurrAddresses->Ipv6IfIndex;
                     if (idx == 0) idx = pCurrAddresses->IfIndex;
                     break;
                }
            }
            pCurrAddresses = pCurrAddresses->Next;
        }
    }
    if (pAddresses) free(pAddresses);
#endif
    return idx;
}

InterfaceContext::~InterfaceContext() {
    if (sock != INVALID_SOCKET) closesocket(sock);
    if (sock_v6 != INVALID_SOCKET) closesocket(sock_v6);
    if (sd_sock != INVALID_SOCKET) closesocket(sd_sock);
    if (sd_sock_v6 != INVALID_SOCKET) closesocket(sd_sock_v6);
    if (tcp_listener != INVALID_SOCKET) closesocket(tcp_listener);
    if (tcp_listener_v6 != INVALID_SOCKET) closesocket(tcp_listener_v6);
}

SomeIpRuntime::SomeIpRuntime(const std::string& config_path, const std::string& instance_name, std::shared_ptr<ILogger> logger) {
    if (logger) this->logger = logger;
    else this->logger = std::make_shared<ConsoleLogger>();
    this->logger->Log(LogLevel::INFO, "Runtime", "Loading config from " + config_path);
    config = ConfigLoader::Load(config_path, instance_name);
    
#ifdef _WIN32
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif

    // Determine default protocol and port for the runtime
    // We'll use the first providing service's endpoint or the instance's main endpoint as "primary"
    std::string primary_iface;
    if (!config.providing.empty()) {
        const auto& svc = config.providing.begin()->second;
        std::string ep_name = svc.endpoint;
        
        // Scan for an interface specifically offered on
        if (ep_name.empty() && !svc.offer_on.empty()) {
            ep_name = svc.offer_on.begin()->second;
        }

        if (!ep_name.empty() && config.endpoints.count(ep_name)) {
            const auto& ep = config.endpoints.at(ep_name);
            this->port = ep.port;
            this->protocol = ep.protocol;
            primary_iface = ep.iface;
        }
    } else if (!config.endpoint.empty() && config.endpoints.count(config.endpoint)) {
        const auto& ep = config.endpoints.at(config.endpoint);
        this->port = ep.port;
        this->protocol = ep.protocol;
        primary_iface = ep.iface;
    }
    for (char &c : protocol) c = std::tolower(c);
    if (protocol.empty()) protocol = "udp";

        // Initialize all interfaces
    for (auto const& [alias, if_cfg] : config.interfaces) {
        auto ctx = std::make_shared<InterfaceContext>();
        ctx->alias = alias;
        ctx->ip = if_cfg.name; // Initial default

        // Resolve Bind IP using unicast_bind > First Unicast Endpoint
        std::string bind_ep_name_v4 = "";
        if (config.unicast_bind.count(alias)) {
            bind_ep_name_v4 = config.unicast_bind.at(alias);
        }

        if (!bind_ep_name_v4.empty() && if_cfg.endpoints.count(bind_ep_name_v4)) {
            const auto& ep = if_cfg.endpoints.at(bind_ep_name_v4);
            if (ep.version == 4) ctx->ip = ep.ip;
        } else {
            // Fallback: Find first unicast IPv4
            for (auto const& [ep_name, ep] : if_cfg.endpoints) {
                 if (ep.version == 4 && ep.ip.find("224.") != 0 && ep.ip.find("239.") != 0) {
                     ctx->ip = ep.ip;
                     break;
                 }
            }
        }

        // IPv6 Bind IP logic
        std::string bind_ep_name_v6 = "";
        // unicast_bind might point to v6? Check if the v4 lookup failed or yielded v6 (unlikely due to map type)
        // unicast_bind might point to v6? Check if the v4 lookup failed or yielded v6 (unlikely due to map type)
        
        if (!bind_ep_name_v6.empty() && if_cfg.endpoints.count(bind_ep_name_v6)) {
             const auto& ep = if_cfg.endpoints.at(bind_ep_name_v6);
             if (ep.version == 6) ctx->ip_v6 = ep.ip;
        } else {
             // Fallback
             for (auto const& [ep_name, ep] : if_cfg.endpoints) {
                 if (ep.version == 6 && ep.ip.find("ff") != 0 && ep.ip.find("FF") != 0) {
                     ctx->ip_v6 = ep.ip;
                     break;
                 }
             }
        }

        // 1. SD Sockets
        if (!if_cfg.sd.endpoint.empty() && if_cfg.endpoints.count(if_cfg.sd.endpoint)) {
            const auto& ep = if_cfg.endpoints.at(if_cfg.sd.endpoint);
            ctx->sd_multicast_ip = ep.ip;
            ctx->sd_multicast_port = ep.port;
            ctx->if_index = ResolveInterfaceIndex(if_cfg.name);

            int reuse = 1;
            ctx->sd_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
            setsockopt(ctx->sd_sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
#ifdef SO_REUSEPORT
            setsockopt(ctx->sd_sock, SOL_SOCKET, SO_REUSEPORT, (const char*)&reuse, sizeof(reuse));
#endif
            
            // Bind SD socket to the local interface IP from config.
            // The fusion tool is responsible for patching this if the platform
            // requires a different bind address (e.g., wildcard on Windows).
            sockaddr_in sd_addr = {0};
            sd_addr.sin_family = AF_INET;
#ifdef _WIN32
            // Windows: Strict binding to the Interface IP (matches verification script)
            sd_addr.sin_addr.s_addr = inet_addr(ctx->ip.c_str());
#else
            // Linux: Bind to Multicast Group IP to allow reception
            // Binding to Unicast IP blocks multicast packets on Linux
            sd_addr.sin_addr.s_addr = inet_addr(ctx->sd_multicast_ip.c_str());
#endif
            sd_addr.sin_port = htons(ctx->sd_multicast_port);
            
#ifndef _WIN32
            // Linux: Apply SO_BINDTODEVICE for strict interface isolation
            // We need the interface name, which we have in if_cfg.name (passed as ctx->alias or similar? No, if_cfg is loop var)
            // ctx has if_index, but SO_BINDTODEVICE needs name.
            // Using if_indextoname as we have index.
            char ifname[IFNAMSIZ];
            if (if_indextoname(ctx->if_index, ifname)) {
                if (setsockopt(ctx->sd_sock, SOL_SOCKET, SO_BINDTODEVICE, ifname, strlen(ifname)) < 0) {
                     // Log warning but continue (might lack CAP_NET_RAW)
                     this->logger->Log(LogLevel::WARN, "Runtime", "Failed to set SO_BINDTODEVICE on " + std::string(ifname));
                }
            }
#endif

            if (bind(ctx->sd_sock, (struct sockaddr*)&sd_addr, sizeof(sd_addr)) < 0) {
                this->logger->Log(LogLevel::WARN, "Runtime", "Failed to bind SD socket on " + alias);
            }

            int loop = 1;
            setsockopt(ctx->sd_sock, IPPROTO_IP, IP_MULTICAST_LOOP, (const char*)&loop, sizeof(loop));
            int ttl = (int)config.sd.multicast_hops;
            setsockopt(ctx->sd_sock, IPPROTO_IP, IP_MULTICAST_TTL, (const char*)&ttl, sizeof(ttl));

            ip_mreq mreq;
            mreq.imr_multiaddr.s_addr = inet_addr(ctx->sd_multicast_ip.c_str());
            mreq.imr_interface.s_addr = inet_addr(ctx->ip.c_str());
            if (setsockopt(ctx->sd_sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, (const char*)&mreq, sizeof(mreq)) < 0) {
                this->logger->Log(LogLevel::WARN, "Runtime", "Failed to join SD group on " + alias);
            }

            // IPv6 SD socket (if endpoint_v6 is configured)
            if (!if_cfg.sd.endpoint_v6.empty() && if_cfg.endpoints.count(if_cfg.sd.endpoint_v6)) {
                const auto& ep6 = if_cfg.endpoints.at(if_cfg.sd.endpoint_v6);
                ctx->sd_multicast_ip_v6 = ep6.ip;
                ctx->sd_multicast_port_v6 = ep6.port;

                int reuse6 = 1;
                ctx->sd_sock_v6 = socket(AF_INET6, SOCK_DGRAM, IPPROTO_UDP);
                setsockopt(ctx->sd_sock_v6, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse6, sizeof(reuse6));
#ifdef SO_REUSEPORT
                setsockopt(ctx->sd_sock_v6, SOL_SOCKET, SO_REUSEPORT, (const char*)&reuse6, sizeof(reuse6));
#endif
                sockaddr_in6 sd_addr6 = {0};
                sd_addr6.sin6_family = AF_INET6;
                sd_addr6.sin6_port = htons(ctx->sd_multicast_port_v6);
#ifdef _WIN32
                // Windows: Bind to in6addr_any to allow sharing
                sd_addr6.sin6_addr = in6addr_any;
#else
                if (!ctx->ip_v6.empty()) {
                    inet_pton(AF_INET6, ctx->ip_v6.c_str(), &sd_addr6.sin6_addr);
                }
#endif
                if (bind(ctx->sd_sock_v6, (struct sockaddr*)&sd_addr6, sizeof(sd_addr6)) < 0) {
                    this->logger->Log(LogLevel::WARN, "Runtime", "Failed to bind IPv6 SD socket on " + alias);
                }

                int loop6 = 1;
                setsockopt(ctx->sd_sock_v6, IPPROTO_IPV6, IPV6_MULTICAST_LOOP, (const char*)&loop6, sizeof(loop6));
                int hops6 = (int)config.sd.multicast_hops;
                setsockopt(ctx->sd_sock_v6, IPPROTO_IPV6, IPV6_MULTICAST_HOPS, (const char*)&hops6, sizeof(hops6));

                // Join IPv6 multicast group
                ipv6_mreq mreq6;
                inet_pton(AF_INET6, ctx->sd_multicast_ip_v6.c_str(), &mreq6.ipv6mr_multiaddr);
                mreq6.ipv6mr_interface = ctx->if_index;
                if (setsockopt(ctx->sd_sock_v6, IPPROTO_IPV6, IPV6_JOIN_GROUP, (const char*)&mreq6, sizeof(mreq6)) < 0) {
                    this->logger->Log(LogLevel::WARN, "Runtime", "Failed to join IPv6 SD group on " + alias);
                }

                // Set multicast interface
                setsockopt(ctx->sd_sock_v6, IPPROTO_IPV6, IPV6_MULTICAST_IF, (const char*)&ctx->if_index, sizeof(ctx->if_index));

                this->logger->Log(LogLevel::INFO, "Runtime", "IPv6 SD listener on " + alias + " (" + ctx->sd_multicast_ip_v6 + ":" + std::to_string(ctx->sd_multicast_port_v6) + ")");
            }
        }

        // 2. Transport Sockets
        ctx->sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        int reuse = 1;
        setsockopt(ctx->sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
        
        sockaddr_in addr = {0};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = inet_addr(ctx->ip.c_str());
        addr.sin_port = htons(this->port);
        if (bind(ctx->sock, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
            this->logger->Log(LogLevel::WARN, "Runtime", "Failed to bind transport socket on " + alias);
        } else if (this->port == 0) {
            // Resolve ephemeral port: read actual bound port from OS
            sockaddr_in bound_addr = {0};
            SOCKLEN_T bound_len = sizeof(bound_addr);
            if (getsockname(ctx->sock, (struct sockaddr*)&bound_addr, &bound_len) == 0) {
                this->port = ntohs(bound_addr.sin_port);
                this->logger->Log(LogLevel::INFO, "Runtime", "Resolved ephemeral UDP port to " + std::to_string(this->port));
            }
        }

        if (protocol == "tcp") {
            ctx->tcp_listener = socket(AF_INET, SOCK_STREAM, 0);
            setsockopt(ctx->tcp_listener, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));
            // For TCP, use the resolved port (which may have been updated from ephemeral above)
            sockaddr_in tcp_addr = {0};
            tcp_addr.sin_family = AF_INET;
            tcp_addr.sin_addr.s_addr = inet_addr(ctx->ip.c_str());
            tcp_addr.sin_port = htons(this->port);
            if (bind(ctx->tcp_listener, (struct sockaddr*)&tcp_addr, sizeof(tcp_addr)) != SOCKET_ERROR) {
                listen(ctx->tcp_listener, 5);
                // Resolve actual TCP port (may differ if port was 0)
                sockaddr_in tcp_bound = {0};
                SOCKLEN_T tcp_bound_len = sizeof(tcp_bound);
                if (getsockname(ctx->tcp_listener, (struct sockaddr*)&tcp_bound, &tcp_bound_len) == 0) {
                    uint16_t actual_tcp_port = ntohs(tcp_bound.sin_port);
                    this->logger->Log(LogLevel::INFO, "Runtime", "TCP listener on " + alias + " bound to port " + std::to_string(actual_tcp_port));
                }
            }
        }

        // Set non-blocking
#ifdef _WIN32
        unsigned long n_mode = 1;
        if (ctx->sock != INVALID_SOCKET) ioctlsocket(ctx->sock, FIONBIO, &n_mode);
        if (ctx->sd_sock != INVALID_SOCKET) ioctlsocket(ctx->sd_sock, FIONBIO, &n_mode);
        if (ctx->tcp_listener != INVALID_SOCKET) ioctlsocket(ctx->tcp_listener, FIONBIO, &n_mode);
#else
        if (ctx->sock != INVALID_SOCKET) fcntl(ctx->sock, F_SETFL, O_NONBLOCK);
        if (ctx->sd_sock != INVALID_SOCKET) fcntl(ctx->sd_sock, F_SETFL, O_NONBLOCK);
        if (ctx->tcp_listener != INVALID_SOCKET) fcntl(ctx->tcp_listener, F_SETFL, O_NONBLOCK);
#endif

        // Populate bound_ports for all endpoints on this interface
        for (auto const& [ep_name, ep] : if_cfg.endpoints) {
            if (ep.ip.find("224.") == 0 || ep.ip.find("239.") == 0 || ep.ip.find("ff") == 0 || ep.ip.find("FF") == 0) continue;
            std::string proto = ep.protocol;
            for (char& c : proto) c = std::tolower(c);
            if (proto == "tcp" && ctx->tcp_listener != INVALID_SOCKET) {
                sockaddr_in tcp_bound = {0};
                SOCKLEN_T tcp_bound_len = sizeof(tcp_bound);
                if (getsockname(ctx->tcp_listener, (struct sockaddr*)&tcp_bound, &tcp_bound_len) == 0) {
                    bound_ports[ep_name] = ntohs(tcp_bound.sin_port);
                }
            } else if (ctx->sock != INVALID_SOCKET) {
                sockaddr_in udp_bound = {0};
                SOCKLEN_T udp_bound_len = sizeof(udp_bound);
                if (getsockname(ctx->sock, (struct sockaddr*)&udp_bound, &udp_bound_len) == 0) {
                    bound_ports[ep_name] = ntohs(udp_bound.sin_port);
                }
            }
        }

        this->interfaces[alias] = ctx;
    }

    if (this->interfaces.empty()) {
        this->logger->Log(LogLevel::ERR, "Runtime", "No interfaces configured!");
        throw std::runtime_error("No interfaces configured");
    }

    running = true;
    reactor_thread = std::jthread(&SomeIpRuntime::Run, this);
}

SomeIpRuntime::~SomeIpRuntime() {
    running = false;
    // jthread automatically joins on destruction
    interfaces.clear(); // Will trigger InterfaceContext destructors (closing sockets)
    {
        std::lock_guard<std::mutex> lock(tcp_clients_mutex);
        for (auto& client : tcp_clients) {
            closesocket(client.first);
        }
        tcp_clients.clear();
    }
#ifdef _WIN32
    WSACleanup();
#endif
}

void SomeIpRuntime::offer_service(const std::string& alias, RequestHandler* impl) {
    if (config.providing.count(alias)) {
        const auto& svc = config.providing.at(alias);
        services[svc.service_id] = impl;

        auto ifaces_to_offer = svc.interfaces;
        if (ifaces_to_offer.empty()) {
            // Default to all interfaces if none specified
            for (auto const& [name, c] : interfaces) ifaces_to_offer.push_back(name);
        }

        for (const auto& if_alias : ifaces_to_offer) {
            if (interfaces.count(if_alias)) {
                auto ctx = interfaces[if_alias];
                
                std::string ep_ip = "";
                std::string ep_ip6 = "";
                uint16_t svc_port = 0;
                std::string svc_proto = "udp";

                if (svc.offer_on.count(if_alias)) {
                    // 1. Explicit Data Plane Endpoint (New Schema)
                    std::string offer_ep_name = svc.offer_on.at(if_alias);
                    bool found_ep = false;
                    // Check instance endpoints first, then interface endpoints (global endpoints are in instance.endpoints)
                    if (config.endpoints.count(offer_ep_name)) {
                        const auto& ep = config.endpoints.at(offer_ep_name);
                        ep_ip = ep.ip;
                        svc_proto = ep.protocol;
                        if (ep.version == 6) ep_ip6 = ep.ip;
                        svc_port = ep.port;
                        found_ep = true;
                    } else if (config.interfaces.count(if_alias) && config.interfaces.at(if_alias).endpoints.count(offer_ep_name)) {
                        const auto& ep = config.interfaces.at(if_alias).endpoints.at(offer_ep_name);
                        ep_ip = ep.ip;
                        svc_proto = ep.protocol;
                        if (ep.version == 6) ep_ip6 = ep.ip;
                        svc_port = ep.port;
                        found_ep = true;
                    }

                    if (found_ep) {
                        // Resolve ephemeral port if needed
                        if (bound_ports.count(offer_ep_name)) {
                             svc_port = bound_ports[offer_ep_name];
                        } else if (svc_port == 0) {
                             svc_port = this->port;
                        }
                    } else {
                        // Config validation should catch this, but runtime safety:
                        this->logger->Log(LogLevel::WARN, "Runtime", "offer_on endpoint '" + offer_ep_name + "' not found for " + if_alias);
                        // Fallback
                        ep_ip = ctx->ip; 
                        svc_port = this->port;
                    }

                } else if (!svc.endpoint.empty() && config.endpoints.count(svc.endpoint)) {
                    // 2. Legacy/Global Endpoint
                    const auto& ep = config.endpoints.at(svc.endpoint);
                    ep_ip = ep.ip;
                    svc_proto = ep.protocol;
                    if (ep.version == 6) ep_ip6 = ep.ip;
                    // Use actual bound port (resolves ephemeral port 0)
                    if (bound_ports.count(svc.endpoint)) {
                        svc_port = bound_ports[svc.endpoint];
                    } else {
                        svc_port = ep.port;
                        if (svc_port == 0) svc_port = this->port;
                    }
                } else {
                    // 3. Fallback to interface's primary IP
                    ep_ip = ctx->ip;
                    svc_port = this->port;
                    svc_proto = this->protocol;
                }

                std::string mcast_ip = "";
                uint16_t mcast_port = 0;
                if (!svc.multicast.empty() && config.endpoints.count(svc.multicast)) {
                    const auto& m_ep = config.endpoints.at(svc.multicast);
                    mcast_ip = m_ep.ip;
                    mcast_port = m_ep.port;
                }

                uint32_t cycle = svc.cycle_offer_ms;
                if (cycle == 0) cycle = config.sd.cycle_offer_ms;

                {
                    std::lock_guard<std::mutex> lock(offered_services_mutex);
                    offered_services.push_back({
                        svc.service_id, svc.instance_id, svc.major_version, svc.minor_version, 
                        svc_port, svc_proto, ep_ip, ep_ip6, mcast_ip, mcast_port, 
                        if_alias, cycle, std::chrono::steady_clock::now()
                    });
                }
                
                SendOffer(svc.service_id, svc.instance_id, svc.major_version, svc.minor_version, svc_port, svc_proto, ctx, ep_ip, ep_ip6, mcast_ip, mcast_port);
                this->logger->Log(LogLevel::INFO, "Runtime", "Offered Service '" + alias + "' on " + if_alias + " (" + ep_ip + ":" + std::to_string(svc_port) + ")");
            }
        }
    }
}

bool SomeIpRuntime::wait_for_service(uint16_t service_id, uint16_t instance_id) {
    int timeout_ms = config.sd.request_timeout_ms;
    auto start = std::chrono::steady_clock::now();
    auto timeout = std::chrono::milliseconds(timeout_ms);
    while (true) {
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - start);
        if (elapsed >= timeout) {
             std::cout << "[Runtime] wait_for_service TIMEOUT after " << elapsed.count() << "ms (limit was " << timeout_ms << "ms)" << std::endl;
             break;
        }
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

void SomeIpRuntime::SendOffer(uint16_t service_id, uint16_t instance_id, uint8_t major, uint32_t minor, uint16_t port, const std::string& protocol, std::shared_ptr<InterfaceContext> ctx, const std::string& endpoint_ip, const std::string& endpoint_ip_v6, const std::string& multicast_ip, uint16_t multicast_port) {
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
        sd_payload.push_back(ipv6 ? 24 : 12); // Length of options (3 + opt_len)
        
        uint8_t proto_id = (protocol == "tcp") ? 0x06 : 0x11;

        if (!ipv6 || endpoint_ip_v6.empty()) {
            sd_payload.push_back(0x00); sd_payload.push_back(0x09); sd_payload.push_back(0x04); sd_payload.push_back(0x00);
            std::string ip_str = endpoint_ip.empty() ? ctx->ip : endpoint_ip;
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
            std::string ip6_str = endpoint_ip_v6.empty() ? ctx->ip_v6 : endpoint_ip_v6;
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

        // SOME/IP header
        uint32_t total_len = (uint32_t)sd_payload.size() + 8;
        std::vector<uint8_t> buffer;
        uint16_t sd_session = next_session(0xFFFF, 0x8100);
        buffer.push_back(0xFF); buffer.push_back(0xFF); buffer.push_back(0x81); buffer.push_back(0x00);
        buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
        buffer.push_back(0x00); buffer.push_back(0x00);
        buffer.push_back(sd_session >> 8); buffer.push_back(sd_session & 0xFF);
        buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00);
        buffer.insert(buffer.end(), sd_payload.begin(), sd_payload.end());
        return buffer;
    };

    if (ctx->sd_sock != INVALID_SOCKET) {
        std::vector<uint8_t> buffer = build_sd(false);
        sockaddr_in dest;
        dest.sin_family = AF_INET;
        dest.sin_addr.s_addr = inet_addr(ctx->sd_multicast_ip.c_str());
        dest.sin_port = htons(ctx->sd_multicast_port);
        int ret = sendto(ctx->sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
        if (ret < 0) {
            this->logger->Log(LogLevel::WARN, "SD", "Failed to send IPv4 Offer for service " + std::to_string(service_id) + " on " + ctx->alias);
        } else {
            this->logger->Log(LogLevel::DEBUG, "SD", "Sent IPv4 Offer for service " + std::to_string(service_id) + " on " + ctx->alias);
        }
    }
    if (ctx->sd_sock_v6 != INVALID_SOCKET && !ctx->sd_multicast_ip_v6.empty()) {
        std::vector<uint8_t> buffer = build_sd(true);
        sockaddr_in6 dest = {0};
        dest.sin6_family = AF_INET6;
        inet_pton(AF_INET6, ctx->sd_multicast_ip_v6.c_str(), &dest.sin6_addr);
        dest.sin6_port = htons(ctx->sd_multicast_port_v6);
        dest.sin6_scope_id = ctx->if_index;
        int ret = sendto(ctx->sd_sock_v6, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
        if (ret < 0) {
            this->logger->Log(LogLevel::WARN, "SD", "Failed to send IPv6 Offer for service " + std::to_string(service_id) + " on " + ctx->alias);
        } else {
            this->logger->Log(LogLevel::DEBUG, "SD", "Sent IPv6 Offer for service " + std::to_string(service_id) + " on " + ctx->alias);
        }
    }
}

std::vector<uint8_t> SomeIpRuntime::SendRequest(uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload, sockaddr_storage target) {
    uint16_t session_id = next_session(service_id, method_id);
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

    std::string if_alias = "";
    for (auto const& [name, client] : config.required) {
        if (client.service_id == service_id) {
            if_alias = client.preferred_interface;
            break;
        }
    }
    if (if_alias.empty() && !interfaces.empty()) if_alias = interfaces.begin()->first;

    if (target_protocol == "tcp") {
        SOCKET client_sock = socket(target.ss_family, SOCK_STREAM, 0);
        if (client_sock != INVALID_SOCKET) {
            if (!if_alias.empty() && interfaces.count(if_alias)) {
                auto ctx = interfaces[if_alias];
                if (target.ss_family == AF_INET) {
                    sockaddr_in local = {0};
                    local.sin_family = AF_INET;
                    local.sin_addr.s_addr = inet_addr(ctx->ip.c_str());
                    bind(client_sock, (struct sockaddr*)&local, sizeof(local));
                } else if (!ctx->ip_v6.empty()) {
                    sockaddr_in6 local6 = {0};
                    local6.sin6_family = AF_INET6;
                    inet_pton(AF_INET6, ctx->ip_v6.c_str(), &local6.sin6_addr);
                    bind(client_sock, (struct sockaddr*)&local6, sizeof(local6));
                }
            }
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
        SOCKET s = INVALID_SOCKET;
        if (!if_alias.empty() && interfaces.count(if_alias)) {
            s = (target.ss_family == AF_INET6) ? interfaces[if_alias]->sock_v6 : interfaces[if_alias]->sock;
        }
        if (s == INVALID_SOCKET) {
            // Pick first available for fallback
            if (!interfaces.empty()) {
                auto first = interfaces.begin()->second;
                s = (target.ss_family == AF_INET6) ? first->sock_v6 : first->sock;
            }
        }

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
    std::string if_alias = "";
    for (auto const& [name, client] : config.required) {
        if (client.service_id == service_id) {
            if_alias = client.preferred_interface;
            break;
        }
    }
    if (if_alias.empty() && !interfaces.empty()) if_alias = interfaces.begin()->first;
    if (if_alias.empty() || !interfaces.count(if_alias)) return;
    auto ctx = interfaces[if_alias];

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
    
    // Endpoint option
    bool is_v6 = (ctx->sd_sock_v6 != INVALID_SOCKET && !ctx->sd_multicast_ip_v6.empty());
    if (is_v6) {
        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(24);
        sd_payload.push_back(0x00); sd_payload.push_back(0x16); sd_payload.push_back(0x06); sd_payload.push_back(0x00);
        sockaddr_in6 sa6; inet_pton(AF_INET6, ctx->ip_v6.c_str(), &sa6.sin6_addr);
        for(int i=0; i<16; i++) sd_payload.push_back(sa6.sin6_addr.s6_addr[i]);
        sd_payload.push_back(0x00); sd_payload.push_back(0x11);
        sd_payload.push_back(this->port >> 8); sd_payload.push_back(this->port & 0xFF);
    } else {
        sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(0x00); sd_payload.push_back(12);
        sd_payload.push_back(0x00); sd_payload.push_back(0x0A); sd_payload.push_back(0x04); sd_payload.push_back(0x00);
        uint32_t lip = ntohl(inet_addr(ctx->ip.c_str()));
        sd_payload.push_back(lip >> 24); sd_payload.push_back(lip >> 16); sd_payload.push_back(lip >> 8); sd_payload.push_back(lip & 0xFF);
        sd_payload.push_back(0x00); sd_payload.push_back(0x11);
        sd_payload.push_back(this->port >> 8); sd_payload.push_back(this->port & 0xFF);
    }

    uint32_t total_len = (uint32_t)sd_payload.size() + 8;
    std::vector<uint8_t> buffer;
    buffer.push_back(0xFF); buffer.push_back(0xFF); buffer.push_back(0x81); buffer.push_back(0x00);
    buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
    uint16_t sess = next_session(0xFFFF, 0x8100);
    buffer.push_back(0x00); buffer.push_back(0x00);
    buffer.push_back(sess >> 8); buffer.push_back(sess & 0xFF);
    buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00);
    buffer.insert(buffer.end(), sd_payload.begin(), sd_payload.end());

    if (is_v6) {
        sockaddr_in6 dest = {0};
        dest.sin6_family = AF_INET6;
        inet_pton(AF_INET6, ctx->sd_multicast_ip_v6.c_str(), &dest.sin6_addr);
        dest.sin6_port = htons(ctx->sd_multicast_port_v6);
        dest.sin6_scope_id = ctx->if_index;
        sendto(ctx->sd_sock_v6, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    } else {
        sockaddr_in dest = {0};
        dest.sin_family = AF_INET;
        dest.sin_addr.s_addr = inet_addr(ctx->sd_multicast_ip.c_str());
        dest.sin_port = htons(ctx->sd_multicast_port);
        sendto(ctx->sd_sock, (const char*)buffer.data(), (int)buffer.size(), 0, (struct sockaddr*)&dest, sizeof(dest));
    }
    subscriptions[{service_id, eventgroup_id}] = false;
    this->logger->Log(LogLevel::DEBUG, "SD", "Sent SubscribeEventgroup for " + std::to_string(service_id) + " on " + if_alias);
}

void SomeIpRuntime::unsubscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id) {
    subscribe_eventgroup(service_id, instance_id, eventgroup_id, 0);
    subscriptions.erase({service_id, eventgroup_id});
}

bool SomeIpRuntime::is_subscription_acked(uint16_t service_id, uint16_t eventgroup_id) {
    auto it = subscriptions.find({service_id, eventgroup_id});
    return it != subscriptions.end() && it->second;
}

void SomeIpRuntime::process_packet(const char* data, int len, sockaddr_storage src, std::shared_ptr<InterfaceContext> ctx, bool is_tcp, SOCKET from_sock) {
#ifdef FUSION_PACKET_DUMP
    DumpPacket(data, (uint32_t)len, src);
#endif
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
                    SOCKET s = from_sock;
                    if (!is_tcp && ctx) {
                        s = (src.ss_family == AF_INET6) ? ctx->sock_v6 : ctx->sock;
                    }
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

void SomeIpRuntime::process_sd_packet(const char* buf, int bytes, sockaddr_storage src, std::shared_ptr<InterfaceContext> ctx) {
#ifdef FUSION_PACKET_DUMP
    DumpPacket(buf, (uint32_t)bytes, src);
#endif
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
        uint8_t maj = uint8_t(buf[offset+8]);
        uint32_t ttl = (uint8_t(buf[offset+9]) << 16) | (uint8_t(buf[offset+10]) << 8) | uint8_t(buf[offset+11]);
        uint32_t min = (uint8_t(buf[offset+12]) << 24) | (uint8_t(buf[offset+13]) << 16) | (uint8_t(buf[offset+14]) << 8) | uint8_t(buf[offset+15]);

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
             
             if (opt_type == 0x04 && (opt_len == 0x09 || opt_len == 0x0A)) { // IPv4 Endpoint
                 sockaddr_in* sin = (sockaddr_in*)&opt_addr;
                 sin->sin_family = AF_INET;
                 memcpy(&sin->sin_addr, &buf[opt_ptr+4], 4);
                 uint16_t opt_port = (uint8_t(buf[opt_ptr+10]) << 8) | uint8_t(buf[opt_ptr+11]);
                 sin->sin_port = htons(opt_port);
             } else if (opt_type == 0x06 && (opt_len == 0x15 || opt_len == 0x16)) { // IPv6 Endpoint
                 sockaddr_in6* sin6 = (sockaddr_in6*)&opt_addr;
                 sin6->sin6_family = AF_INET6;
                 memcpy(&sin6->sin6_addr, &buf[opt_ptr+4], 16);
                 uint16_t opt_port = (uint8_t(buf[opt_ptr+20]) << 8) | uint8_t(buf[opt_ptr+21]);
                 sin6->sin6_port = htons(opt_port);
             }
             parsed_opts.push_back(opt_addr);
             opt_ptr += 3 + opt_len; // Length field excludes Type
        }

        if (index1 < parsed_opts.size()) {
            endpoint = parsed_opts[index1];
            if (endpoint.ss_family == AF_INET && ((sockaddr_in*)&endpoint)->sin_port != 0) has_endpoint = true;
            else if (endpoint.ss_family == AF_INET6 && ((sockaddr_in6*)&endpoint)->sin6_port != 0) has_endpoint = true;
        }

        if (type == 0x01 && ttl > 0) { // Offer
            if (has_endpoint) {
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
            uint16_t eventgroup_id = (uint16_t)(min >> 16);
            std::pair<uint16_t, uint16_t> key = {sid, eventgroup_id};
            bool is_offered = false;
            uint16_t found_iid = 1;
            {
                std::lock_guard<std::mutex> lock(offered_services_mutex);
                for(auto& off : offered_services) {
                    if (off.service_id == sid && off.iface_alias == ctx->alias) { is_offered = true; found_iid = off.instance_id; }
                }
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
                        this->logger->Log(LogLevel::INFO, "SD", "New Subscriber for "+std::to_string(sid)+" EG "+std::to_string(eventgroup_id) + " on " + ctx->alias);
                        
                        std::vector<uint8_t> ack_payload;
                        ack_payload.push_back(0x80); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00);
                        ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(16);
                        ack_payload.push_back(0x07); // Subscribe ACK
                        ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); 
                        ack_payload.push_back((sid >> 8) & 0xFF); ack_payload.push_back(sid & 0xFF);
                        ack_payload.push_back((found_iid >> 8) & 0xFF); ack_payload.push_back(found_iid & 0xFF);
                        ack_payload.push_back(maj); // Major Version
                        ack_payload.push_back((ttl >> 16) & 0xFF); ack_payload.push_back((ttl >> 8) & 0xFF); ack_payload.push_back(ttl & 0xFF); // TTL
                        ack_payload.push_back((min >> 24) & 0xFF); ack_payload.push_back((min >> 16) & 0xFF); ack_payload.push_back((min >> 8) & 0xFF); ack_payload.push_back(min & 0xFF);
                        ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); ack_payload.push_back(0x00); 
                        
                        uint32_t total_len = (uint32_t)ack_payload.size() + 8;
                        std::vector<uint8_t> abuf;
                        abuf.push_back(0xFF); abuf.push_back(0xFF); abuf.push_back(0x81); abuf.push_back(0x00);
                        abuf.push_back(total_len >> 24); abuf.push_back(total_len >> 16); abuf.push_back(total_len >> 8); abuf.push_back(total_len);
                        
                        uint16_t d_session = next_session(0xFFFF, 0x8100);
                        abuf.push_back(0x00); abuf.push_back(0x00);
                        abuf.push_back(d_session >> 8); abuf.push_back(d_session & 0xFF);
                        abuf.push_back(0x01); abuf.push_back(0x01); abuf.push_back(0x02); abuf.push_back(0x00);
                        abuf.insert(abuf.end(), ack_payload.begin(), ack_payload.end());

                        if (src.ss_family == AF_INET) {
                            sendto(ctx->sd_sock, (const char*)abuf.data(), (int)abuf.size(), 0, (struct sockaddr*)&src, sizeof(sockaddr_in));
                        } else {
                            sendto(ctx->sd_sock_v6, (const char*)abuf.data(), (int)abuf.size(), 0, (struct sockaddr*)&src, sizeof(sockaddr_in6));
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

#ifdef FUSION_PACKET_DUMP
void SomeIpRuntime::DumpPacket(const char* data, uint32_t len, sockaddr_storage src) {
    if (len < 16) return;
    uint16_t sid = (uint8_t(data[0]) << 8) | uint8_t(data[1]);
    uint16_t mid = (uint8_t(data[2]) << 8) | uint8_t(data[3]);
    uint32_t length = (uint8_t(data[4]) << 24) | (uint8_t(data[5]) << 16) | (uint8_t(data[6]) << 8) | uint8_t(data[7]);
    uint16_t cid = (uint8_t(data[8]) << 8) | uint8_t(data[9]);
    uint16_t ssid = (uint8_t(data[10]) << 8) | uint8_t(data[11]);
    uint8_t pv = data[12];
    uint8_t iv = data[13];
    uint8_t mt = data[14];
    uint8_t rc = data[15];

    char ip_str[INET6_ADDRSTRLEN];
    uint16_t out_port = 0;
    if (src.ss_family == AF_INET) {
        inet_ntop(AF_INET, &((sockaddr_in*)&src)->sin_addr, ip_str, INET_ADDRSTRLEN);
        out_port = ntohs(((sockaddr_in*)&src)->sin_port);
    } else {
        inet_ntop(AF_INET6, &((sockaddr_in6*)&src)->sin6_addr, ip_str, INET6_ADDRSTRLEN);
        out_port = ntohs(((sockaddr_in6*)&src)->sin6_port);
    }

    std::string mt_str = (mt == 0x00) ? "REQ" : (mt == 0x01) ? "REQ_NO_RET" : (mt == 0x02) ? "NOTIF" : (mt == 0x80) ? "RESP" : (mt == 0x81) ? "ERR" : "0x" + std::to_string(mt);
    
    char sid_h[5], mid_h[5], cid_h[5], ssid_h[5];
    snprintf(sid_h, 5, "%04X", sid);
    snprintf(mid_h, 5, "%04X", mid);
    snprintf(cid_h, 5, "%04X", cid);
    snprintf(ssid_h, 5, "%04X", ssid);

    this->logger->Log(LogLevel::DEBUG, "DUMP", "\n[DUMP] --- SOME/IP Message from " + std::string(ip_str) + ":" + std::to_string(out_port) + " ---");
    this->logger->Log(LogLevel::DEBUG, "DUMP", "  [Header] Service:0x" + std::string(sid_h) + " Method:0x" + std::string(mid_h) + " Len:" + std::to_string(length) + " Client:0x" + std::string(cid_h) + " Session:0x" + std::string(ssid_h));
    this->logger->Log(LogLevel::DEBUG, "DUMP", "  [Header] Proto:v" + std::to_string(pv) + " Iface:v" + std::to_string(iv) + " Type:" + mt_str + " Return:0x" + std::to_string(rc));

    if (sid == 0xFFFF && mid == 0x8100) {
        if (len >= 24) {
            uint32_t e_len = (uint8_t(data[20]) << 24) | (uint8_t(data[21]) << 16) | (uint8_t(data[22]) << 8) | uint8_t(data[23]);
            uint32_t offset = 24;
            uint32_t entries_end = offset + e_len;
            if (entries_end > len) entries_end = len;
            
            while (offset + 16 <= entries_end) {
                uint8_t etype = (uint8_t)data[offset];
                uint16_t esid = (uint8_t(data[offset+4]) << 8) | uint8_t(data[offset+5]);
                uint16_t eiid = (uint8_t(data[offset+6]) << 8) | uint8_t(data[offset+7]);
                uint8_t emaj = uint8_t(data[offset+8]);
                uint32_t ettl = (uint8_t(data[offset+9]) << 16) | (uint8_t(data[offset+10]) << 8) | uint8_t(data[offset+11]);
                
                std::string tname = (etype == 0x00) ? "FindService" : (etype == 0x01) ? "OfferService" : (etype == 0x06) ? "Subscribe" : (etype == 0x07) ? "SubAck" : "0x" + std::to_string(etype);
                char esid_h[5], eiid_h[5];
                snprintf(esid_h, 5, "%04X", esid);
                snprintf(eiid_h, 5, "%04X", eiid);
                
                this->logger->Log(LogLevel::DEBUG, "DUMP", "  [Entry] " + tname + ": Service=0x" + std::string(esid_h) + " Inst=0x" + std::string(eiid_h) + " Maj=" + std::to_string(emaj) + " TTL=" + std::to_string(ettl));
                offset += 16;
            }
            
            if (offset + 4 <= (uint32_t)len) {
                uint32_t o_len = (uint8_t(data[offset]) << 24) | (uint8_t(data[offset+1]) << 16) | (uint8_t(data[offset+2]) << 8) | uint8_t(data[offset+3]);
                offset += 4;
                uint32_t options_end = offset + o_len;
                while (offset + 3 <= options_end && offset < (uint32_t)len) {
                    uint16_t ol = (uint8_t(data[offset]) << 8) | uint8_t(data[offset+1]);
                    uint8_t ot = (uint8_t)data[offset+2];
                    
                    if ((ot == 0x04 || ot == 0x14) && offset + 12 <= (uint32_t)len) {
                        char oip[INET_ADDRSTRLEN];
                        inet_ntop(AF_INET, data + offset + 4, oip, INET_ADDRSTRLEN);
                        uint16_t port = (uint8_t(data[offset+10]) << 8) | uint8_t(data[offset+11]);
                        std::string proto = (data[offset+9] == 0x06) ? "TCP" : "UDP";
                        std::string oname = (ot == 0x04) ? "IPv4 Endpt" : "IPv4 Multicast";
                        this->logger->Log(LogLevel::DEBUG, "DUMP", "  [Option] " + oname + ": " + std::string(oip) + ":" + std::to_string(port) + " (" + proto + ")");
                    } else if ((ot == 0x06 || ot == 0x16) && offset + 24 <= (uint32_t)len) {
                        char oip[INET6_ADDRSTRLEN];
                        inet_ntop(AF_INET6, data + offset + 4, oip, INET6_ADDRSTRLEN);
                        uint16_t port = (uint8_t(data[offset+22]) << 8) | uint8_t(data[offset+23]);
                        std::string proto = (data[offset+21] == 0x06) ? "TCP" : "UDP";
                        std::string oname = (ot == 0x06) ? "IPv6 Endpt" : "IPv6 Multicast";
                        this->logger->Log(LogLevel::DEBUG, "DUMP", "  [Option] " + oname + ": " + std::string(oip) + ":" + std::to_string(port) + " (" + proto + ")");
                    }
                    offset += 2 + ol;
                }
            }
        }
    }
    this->logger->Log(LogLevel::DEBUG, "DUMP", "--------------------------------------\n");
}
#endif

void SomeIpRuntime::Run() {
    char buf[4096];
    while (running) {
        auto now = std::chrono::steady_clock::now();
        
        // Multi-interface sending of cyclic offers
        {
            std::lock_guard<std::mutex> lock(offered_services_mutex);
            for (auto& svc : offered_services) {
                if (std::chrono::duration_cast<std::chrono::milliseconds>(now - svc.last_offer_time).count() > (long long)svc.cycle_offer_ms) {
                    svc.last_offer_time = now;
                    if (interfaces.count(svc.iface_alias)) {
                        SendOffer(svc.service_id, svc.instance_id, svc.major_version, svc.minor_version, svc.port, svc.protocol, interfaces[svc.iface_alias], svc.endpoint_ip, svc.endpoint_ip_v6, svc.multicast_ip, svc.multicast_port);
                    }
                }
            }
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        SOCKET max_fd = 0;
        
        auto add_sock = [&](SOCKET s) {
            if (s != INVALID_SOCKET) {
                FD_SET(s, &readfds);
                if ((int)s > (int)max_fd) max_fd = s;
            }
        };

        for (auto const& [name, ctx] : interfaces) {
            add_sock(ctx->sock);
            add_sock(ctx->sock_v6);
            add_sock(ctx->sd_sock);
            add_sock(ctx->sd_sock_v6);
            add_sock(ctx->tcp_listener);
            add_sock(ctx->tcp_listener_v6);
        }
        
        {
            std::lock_guard<std::mutex> lock(tcp_clients_mutex);
            for (auto& client : tcp_clients) {
                add_sock(client.first);
            }
        }

        timeval timeout;
        timeout.tv_sec = 0;
        timeout.tv_usec = 100000;
        int activity = select((int)max_fd + 1, &readfds, NULL, NULL, &timeout);

        if (activity <= 0) continue;

        for (auto const& [name, ctx] : interfaces) {
            if (ctx->sd_sock != INVALID_SOCKET && FD_ISSET(ctx->sd_sock, &readfds)) {
                sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
                int bytes = recvfrom(ctx->sd_sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
                if (bytes > 0) process_sd_packet(buf, bytes, src, ctx);
            }
            if (ctx->sd_sock_v6 != INVALID_SOCKET && FD_ISSET(ctx->sd_sock_v6, &readfds)) {
                sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
                int bytes = recvfrom(ctx->sd_sock_v6, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
                if (bytes > 0) process_sd_packet(buf, bytes, src, ctx);
            }
            if (ctx->sock != INVALID_SOCKET && FD_ISSET(ctx->sock, &readfds)) {
                sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
                int bytes = recvfrom(ctx->sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
                if (bytes > 0) process_packet(buf, bytes, src, ctx, false);
            }
            if (ctx->sock_v6 != INVALID_SOCKET && FD_ISSET(ctx->sock_v6, &readfds)) {
                sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
                int bytes = recvfrom(ctx->sock_v6, buf, sizeof(buf), 0, (struct sockaddr*)&src, &sl);
                if (bytes > 0) process_packet(buf, bytes, src, ctx, false);
            }

            if (ctx->tcp_listener != INVALID_SOCKET && FD_ISSET(ctx->tcp_listener, &readfds)) {
                sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
                SOCKET client = accept(ctx->tcp_listener, (struct sockaddr*)&src, &sl);
                if (client != INVALID_SOCKET) {
                    std::lock_guard<std::mutex> lock(tcp_clients_mutex);
                    tcp_clients.push_back({client, src});
                }
            }
            if (ctx->tcp_listener_v6 != INVALID_SOCKET && FD_ISSET(ctx->tcp_listener_v6, &readfds)) {
                sockaddr_storage src; SOCKLEN_T sl = sizeof(src);
                SOCKET client = accept(ctx->tcp_listener_v6, (struct sockaddr*)&src, &sl);
                if (client != INVALID_SOCKET) {
                    std::lock_guard<std::mutex> lock(tcp_clients_mutex);
                    tcp_clients.push_back({client, src});
                }
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
                process_packet(buf, bytes, it->second, nullptr, true, it->first);
            }
            ++it;
        }
    }
}

void SomeIpRuntime::SendNotification(uint16_t service_id, uint16_t event_id, const std::vector<uint8_t>& payload) {
    std::vector<std::shared_ptr<InterfaceContext>> offering_ifaces;
    {
        std::lock_guard<std::mutex> lock(offered_services_mutex);
        for (const auto& off : offered_services) {
            if (off.service_id == service_id && interfaces.count(off.iface_alias)) {
                bool already = false;
                for(auto const& ex : offering_ifaces) if(ex == interfaces[off.iface_alias]) already = true;
                if(!already) offering_ifaces.push_back(interfaces[off.iface_alias]);
            }
        }
    }

    if (offering_ifaces.empty()) return;

    std::lock_guard<std::mutex> lock(subscribers_mutex);

    for (const auto& [key, sub_list] : subscribers) {
        if (key.first != service_id) continue;
        
        uint16_t session_id = next_session(service_id, event_id);
        uint32_t total_len = (uint32_t)payload.size() + 8;
        std::vector<uint8_t> buffer;
        buffer.push_back(service_id >> 8); buffer.push_back(service_id & 0xFF);
        buffer.push_back(event_id >> 8); buffer.push_back(event_id & 0xFF); 
        buffer.push_back(total_len >> 24); buffer.push_back(total_len >> 16); buffer.push_back(total_len >> 8); buffer.push_back(total_len);
        buffer.push_back(0x00); buffer.push_back(0x00);
        buffer.push_back(session_id >> 8); buffer.push_back(session_id & 0xFF);
        buffer.push_back(0x01); buffer.push_back(0x01); buffer.push_back(0x02); buffer.push_back(0x00);
        buffer.insert(buffer.end(), payload.begin(), payload.end());

        for (const auto& sub : sub_list) {
            char sub_ip[INET6_ADDRSTRLEN];
            uint16_t sub_port = 0;
            if(sub.ss_family == AF_INET) {
                inet_ntop(AF_INET, &((sockaddr_in*)&sub)->sin_addr, sub_ip, INET_ADDRSTRLEN);
                sub_port = ntohs(((sockaddr_in*)&sub)->sin_port);
            } else {
                inet_ntop(AF_INET6, &((sockaddr_in6*)&sub)->sin6_addr, sub_ip, INET6_ADDRSTRLEN);
                sub_port = ntohs(((sockaddr_in6*)&sub)->sin6_port);
            }

            for (auto const& ctx : offering_ifaces) {
                SOCKET s = (sub.ss_family == AF_INET6) ? ctx->sock_v6 : ctx->sock;
                int sl = (sub.ss_family == AF_INET6) ? sizeof(sockaddr_in6) : sizeof(sockaddr_in);
                if (s != INVALID_SOCKET) {
                    this->logger->Log(LogLevel::DEBUG, "Runtime", "Sending Notification to " + std::string(sub_ip) + ":" + std::to_string(sub_port));
                    sendto(s, (const char*)buffer.data(), (int)buffer.size(), 0, (const struct sockaddr*)&sub, sl);
                }
            }
        }
    }
}

// Implementation of SendRequestGlue
std::vector<uint8_t> SendRequestGlue(void* rt_ptr, uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload) {
    SomeIpRuntime* rt = (SomeIpRuntime*)rt_ptr;
    if (!rt) return {};
    
    // Find target via SD
    sockaddr_storage target;
    {
         int retries = 0;
         int max_retries = rt->config.sd.request_timeout_ms / 100;
         while (!rt->get_remote_service(service_id, 0xFFFF, target) && retries < max_retries) {
              std::this_thread::sleep_for(std::chrono::milliseconds(100));
              retries++;
         }
         if (retries >= max_retries) {
              if (!rt->get_remote_service(service_id, 0xFFFF, target)) {
                  if(rt->logger) rt->logger->Log(LogLevel::WARN, "Glue", "Service not found 0x" + std::to_string(service_id));
                  return {};
              }
         }
    }

    if(rt->logger) rt->logger->Log(LogLevel::DEBUG, "Glue", "Sending Request...");
    // SendRequest already handles PendingRequest creation and waiting
    return rt->SendRequest(service_id, method_id, payload, target);
}


} // namespace fusion_hawking
