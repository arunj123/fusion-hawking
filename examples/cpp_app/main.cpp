#include <iostream>
#include <vector>
#include <map>
#include <string>
#include <thread>
#include <chrono>
#include <algorithm>
#include <memory> 

#include <fusion_hawking/runtime.hpp>
#include "bindings.h" // Generated bindings

using namespace fusion_hawking;
using namespace generated;

// --- Sort Service Implementation ---
class SortServiceImpl : public SortServiceStub {
    std::shared_ptr<ILogger> logger;
public:
    SortServiceImpl(std::shared_ptr<ILogger> logger, SomeIpRuntime* runtime) : logger(logger), runtime(runtime) {}
    
    // Field Storage
    std::string current_status = "Idle";
    
    virtual SortServiceSortAscResponse SortAsc(SortServiceSortAscRequest req) override {
        current_status = "Sorting Ascending";
        if (logger) logger->Log(LogLevel::DEBUG, "SortService", "Sorting " + std::to_string(req.data.size()) + " items");
        std::sort(req.data.begin(), req.data.end());
        
        current_status = "Sorting Ascending";
        logger->Log(LogLevel::INFO, "SortService", "Field 'status' changed: " + current_status);

        // Fire Event: on_sort_completed
        // We'll broadcast to all subscribers of eventgroup 1 for this Service (SortService = 0x3001)
        SortServiceOnSortCompletedEvent evt;
        evt.count = (int32_t)req.data.size();
        auto payload = evt.serialize();
        
        // 0x8001 is the ID of on_sort_completed
        runtime->SendNotification(SortServiceStub::SERVICE_ID, 0x8001, payload);
        
        SortServiceSortAscResponse res;
        res.result = req.data;
        
        current_status = "Idle";
        logger->Log(LogLevel::INFO, "SortService", "Field 'status' changed: " + current_status);
        return res;
    }
    
    virtual SortServiceSortDescResponse SortDesc(SortServiceSortDescRequest req) override {
         current_status = "Sorting Descending";
         std::sort(req.data.begin(), req.data.end(), std::greater<int>());
         SortServiceSortDescResponse res;
         res.result = req.data;
         
         current_status = "Idle";
         return res;
    }

private:
    SomeIpRuntime* runtime;
};

int main() {
    auto logger = std::make_shared<ConsoleLogger>();
    logger->Log(LogLevel::INFO, "Main", "Starting C++ Demo (Core Library)");
    
    // 1. Initialize
    SomeIpRuntime rt("examples/config.json", "cpp_app_instance", logger);
    
    // 2. Offer
    SortServiceImpl sort_svc(logger, &rt);
    rt.offer_service("sort-service", &sort_svc);
    
    // 3. Client
    std::this_thread::sleep_for(std::chrono::seconds(2));
    MathServiceClient* client = rt.create_client<MathServiceClient>("math-client");
    
    while (true) {
        if (client) {
            logger->Log(LogLevel::INFO, "Client", "Sending Add(5, 5)...");
            client->Add(5, 5);
            logger->Log(LogLevel::INFO, "Client", "Add Request Sent");
        } else {
            // Try to reconnect if null
            client = rt.create_client<MathServiceClient>("math-client", 1000);
        }
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
    
    return 0;
}
