#pragma once
#include <string>
#include <vector>
#include <map>
#include <thread>
#include <chrono>
#include <atomic>
#include <mutex>
#include <condition_variable>
#include <memory>
#include "types.hpp"
#include "logger.hpp"
#include "config.hpp"

#ifdef _WIN32
#include <winsock2.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#define SOCKET int
#define INVALID_SOCKET -1
#define SOCKET_ERROR -1
#endif

namespace fusion_hawking {

class SomeIpRuntime {
    SOCKET sock;
    SOCKET sock_v6 = INVALID_SOCKET;
    SOCKET sd_sock;
    SOCKET sd_sock_v6 = INVALID_SOCKET;
    SOCKET tcp_listener = INVALID_SOCKET;
    SOCKET tcp_listener_v6 = INVALID_SOCKET;
    std::vector<std::pair<SOCKET, sockaddr_storage>> tcp_clients;
    std::mutex tcp_clients_mutex;
    std::string protocol;
    
    std::atomic<bool> running;
    std::jthread reactor_thread;
    uint16_t port;
    std::map<uint16_t, RequestHandler*> services;
    std::map<std::pair<uint16_t, uint16_t>, sockaddr_storage> remote_services;
    std::mutex remote_services_mutex;
    
    InstanceConfig config;
    std::shared_ptr<ILogger> logger;
    
    std::string sd_multicast_ip = "";
    uint16_t sd_multicast_port = 30490;
    std::string sd_multicast_ip_v6 = "";
    uint16_t sd_multicast_port_v6 = 30490;
    unsigned int sd_if_index = 0;

public:
    SomeIpRuntime(const std::string& config_path, const std::string& instance_name, std::shared_ptr<ILogger> logger = nullptr);
    ~SomeIpRuntime();

    void offer_service(const std::string& alias, RequestHandler* impl);
    
    template <typename T>
    T* create_client(const std::string& alias) { // Removed hardcoded timeout argument, use config
        uint16_t service_id = T::SERVICE_ID;
        uint16_t instance_id = 0xFFFF;
        // Resolve from config if available
        if (config.required.find(alias) != config.required.end()) {
            service_id = config.required[alias].service_id;
            instance_id = config.required[alias].instance_id;
        }
        // Wait for service discovery
        if (wait_for_service(service_id, instance_id)) {
            return new T(this, service_id);
        }
        if (logger) logger->Log(LogLevel::WARN, "Runtime", "Timeout waiting for service '" + alias + "'");
        return nullptr;
    }

    void SendOffer(uint16_t service_id, uint16_t instance_id, uint8_t major, uint32_t minor, uint16_t port, const std::string& protocol = "udp", const std::string& endpoint_ip = "", const std::string& endpoint_ip_v6 = "", const std::string& multicast_ip = "", uint16_t multicast_port = 0);
    std::vector<uint8_t> SendRequest(uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload, sockaddr_storage target);
    void SendNotification(uint16_t service_id, uint16_t event_id, const std::vector<uint8_t>& payload);
    bool get_remote_service(uint16_t service_id, uint16_t instance_id, sockaddr_storage& out);
    
    // Event subscription
    void subscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id, uint32_t ttl = 0xFFFFFF);
    void unsubscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id);
    bool is_subscription_acked(uint16_t service_id, uint16_t eventgroup_id);
    
    SOCKET get_sock() const { return sock; }

    bool wait_for_service(uint16_t service_id, uint16_t instance_id);

private:
    void Run();
    void process_packet(const char* data, int len, sockaddr_storage src, SOCKET from_sock, bool is_tcp);
    void process_sd_packet(const char* data, int len, sockaddr_storage src);
    
    struct OfferedServiceInfo {
        uint16_t service_id;
        uint16_t instance_id;
        uint8_t major_version;
        uint32_t minor_version;
        uint16_t port;
        std::string protocol;
        std::string endpoint_ip;
        std::string endpoint_ip_v6;
        std::string multicast_ip;
        uint16_t multicast_port;
    };
    std::vector<OfferedServiceInfo> offered_services;
    
    std::chrono::steady_clock::time_point last_offer_time;
    std::map<std::pair<uint16_t, uint16_t>, bool> subscriptions; // (service_id, eventgroup_id) -> acked
    
    // Server-side: Subscribers for my events
    // (service_id, eventgroup_id) -> list of subscriber addresses
    std::map<std::pair<uint16_t, uint16_t>, std::vector<sockaddr_storage>> subscribers; 
    std::mutex subscribers_mutex;

    // Pending requests
    struct PendingRequest {
        std::vector<uint8_t> payload;
        bool completed = false;
        std::condition_variable cv;
        std::mutex mtx;
    };
    std::map<std::tuple<uint16_t, uint16_t, uint16_t>, std::shared_ptr<PendingRequest>> pending_requests;
    std::mutex pending_requests_mutex;

    // SendRequestGlue Declaration within Runtime to access privates
    friend std::vector<uint8_t> SendRequestGlue(void* rt, uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload);
};

// Moving SendRequestGlue out of header or forward declaring it


} // namespace fusion_hawking
