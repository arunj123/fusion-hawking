#pragma once
#include <string>
#include <vector>
#include <map>
#include <thread>
#include <chrono>
#include <atomic>
#include <mutex>
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
#endif

namespace fusion_hawking {

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
    SomeIpRuntime(const std::string& config_path, const std::string& instance_name, std::shared_ptr<ILogger> logger = nullptr);
    ~SomeIpRuntime();

    void offer_service(const std::string& alias, RequestHandler* impl);
    
    template <typename T>
    T* create_client(const std::string& alias, int timeout_ms = 5000) {
        uint16_t service_id = T::SERVICE_ID;
        // Resolve from config if available
        if (config.required.find(alias) != config.required.end()) {
            service_id = config.required[alias].service_id;
        }
        // Wait for service discovery
        if (wait_for_service(service_id, timeout_ms)) {
            return new T(this, service_id);
        }
        if (logger) logger->Log(LogLevel::WARN, "Runtime", "Timeout waiting for service '" + alias + "'");
        return nullptr;
    }

    void SendOffer(uint16_t service_id, uint16_t instance_id, uint16_t port);
    void SendRequest(uint16_t service_id, uint16_t method_id, const std::vector<uint8_t>& payload, sockaddr_in target);
    void SendNotification(uint16_t service_id, uint16_t event_id, const std::vector<uint8_t>& payload);
    bool get_remote_service(uint16_t service_id, sockaddr_in& out);
    
    // Event subscription
    void subscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id, uint32_t ttl = 0xFFFFFF);
    void unsubscribe_eventgroup(uint16_t service_id, uint16_t instance_id, uint16_t eventgroup_id);
    bool is_subscription_acked(uint16_t service_id, uint16_t eventgroup_id);
    
    SOCKET get_sock() const { return sock; }

    bool wait_for_service(uint16_t service_id, int timeout_ms = 5000);

private:
    void Run();
    std::vector<std::tuple<uint16_t, uint16_t, uint16_t>> offered_services; // (svc_id, inst_id, port)
    std::chrono::steady_clock::time_point last_offer_time;
    std::map<std::pair<uint16_t, uint16_t>, bool> subscriptions; // (service_id, eventgroup_id) -> acked
    
    // Server-side: Subscribers for my events
    // (service_id, eventgroup_id) -> list of subscriber addresses
    std::map<std::pair<uint16_t, uint16_t>, std::vector<sockaddr_in>> subscribers; 

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
