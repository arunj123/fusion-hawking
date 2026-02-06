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
    
    virtual SortServiceSortAscResponse SortAsc(SortServiceSortAscRequest req) override {
        if (logger) logger->Log(LogLevel::DEBUG, "SortService", "Sorting " + std::to_string(req.data.size()) + " items");
        SetStatus("Sorting...");
        std::sort(req.data.begin(), req.data.end());
        SetStatus("Ready");
        
        SortServiceOnSortCompletedEvent evt;
        evt.count = (int32_t)req.data.size();
        
        // Use Generated Constants
        runtime->SendNotification(SERVICE_ID, EVENT_ON_SORT_COMPLETED, evt.serialize());
        
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

    // Field Implementation
    std::string status = "Ready";
    
    virtual std::string GetStatus() override {
        return status;
    }
    
    virtual void SetStatus(std::string val) override {
        status = val;
        std::cout << "DEBUG: SetStatus called with " << val << std::endl;
        if (logger) logger->Log(LogLevel::INFO, "SortService", "Field 'status' changed to: " + val);
    }

private:
    SomeIpRuntime* runtime;
};

// --- Sensor Service Implementation ---
class SensorServiceImpl : public SensorServiceStub {
public:
    float temp = 25.0f;
    SensorServiceImpl(SomeIpRuntime* rt) : runtime(rt) {}
    
    void Update() {
        temp += 0.1f;
        SensorServiceOnValueChangedEvent evt;
        evt.value = temp;
        runtime->SendNotification(SERVICE_ID, EVENT_ON_VALUE_CHANGED, evt.serialize());
    }

    virtual float GetTemperature() override {
        return temp;
    }

private:
    SomeIpRuntime* runtime;
};

int main() {
    auto logger = std::make_shared<ConsoleLogger>();
    logger->Log(LogLevel::INFO, "Main", "Starting C++ Demo (Core Library)");
    
    // Load config from parent directory in the integrated_apps bundle
    SomeIpRuntime rt("../config.json", "cpp_app_instance", logger);
    
    SortServiceImpl sort_svc(logger, &rt);
    rt.offer_service("sort-service", &sort_svc);

    SensorServiceImpl sensor_svc(&rt);
    rt.offer_service("sensor-service", &sensor_svc);
    
    std::this_thread::sleep_for(std::chrono::seconds(2));
    MathServiceClient* client = rt.create_client<MathServiceClient>("math-client");
    
    while (true) {
        sensor_svc.Update();
        if (client) {
            auto res = client->Add(rand() % 100, rand() % 100);
            logger->Log(LogLevel::INFO, "Main", "Math.Add Result: " + std::to_string(res.result));
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    return 0;
}
