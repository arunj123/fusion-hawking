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

// --- Math Service Implementation ---
class MathServiceImpl : public MathServiceStub {
    std::shared_ptr<ILogger> logger;
    int instance_id;
public:
    MathServiceImpl(std::shared_ptr<ILogger> logger, int instance_id) : logger(logger), instance_id(instance_id) {}
    
    virtual MathServiceAddResponse Add(MathServiceAddRequest req) override {
        if (logger) logger->Log(LogLevel::INFO, "MathService", "[" + std::to_string(instance_id) + "] Add(" + std::to_string(req.a) + ", " + std::to_string(req.b) + ")");
        MathServiceAddResponse res;
        res.result = req.a + req.b;
        return res;
    }
    
    virtual MathServiceSubResponse Sub(MathServiceSubRequest req) override {
        MathServiceSubResponse res;
        res.result = req.a - req.b;
        return res;
    }
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
    
    MathServiceImpl math_svc(logger, 2);
    rt.offer_service("math-service", &math_svc);
    
    std::this_thread::sleep_for(std::chrono::seconds(2));
    std::shared_ptr<MathServiceClient> client = nullptr;

    // Retry loop for client creation will happen in main loop
    
    while (true) {
        sensor_svc.Update();
        
        if (!client) {
            // Try to create client if not exists
            // Since create_client might block or log warning, we try periodically
             try {
                // We use specific method if available, or just create_client
                // If create_client returns raw pointer, we manage it. 
                // The original code used raw pointer: MathServiceClient* client = ...
                // generated bindings probably return raw pointer (owned by runtime?) or unique_ptr?
                // checked main.cpp: MathServiceClient* client = rt.create_client<...>();
                // If it fails, it returns nullptr?
                client.reset(rt.create_client<MathServiceClient>("math-client"));
             } catch (...) {
                 // Ignore
             }
        }

        if (client) {
            auto res = client->Add(rand() % 100, rand() % 100);
            logger->Log(LogLevel::INFO, "Main", "Math.Add Result: " + std::to_string(res.result));
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    return 0;
}
