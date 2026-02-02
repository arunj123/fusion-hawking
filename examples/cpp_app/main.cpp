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
    SortServiceImpl(std::shared_ptr<ILogger> logger) : logger(logger) {}
    virtual SortServiceSortAscResponse SortAsc(SortServiceSortAscRequest req) override {
        if (logger) logger->Log(LogLevel::DEBUG, "SortService", "Sorting " + std::to_string(req.data.size()) + " items");
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
    logger->Log(LogLevel::INFO, "Main", "Starting C++ Demo (Core Library)");
    
    // 1. Initialize
    SomeIpRuntime rt("examples/config.json", "cpp_app_instance", logger);
    
    // 2. Offer
    SortServiceImpl sort_svc(logger);
    rt.offer_service("sort-service", &sort_svc);
    
    // 3. Client
    std::this_thread::sleep_for(std::chrono::seconds(2));
    MathServiceClient* client = rt.create_client<MathServiceClient>("math-client");
    
    while (true) {
        logger->Log(LogLevel::INFO, "Client", "Sending Add(5, 5)...");
        client->Add(5, 5);
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
    
    return 0;
}
