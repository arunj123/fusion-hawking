/**
 * Automotive Pub-Sub Demo: Radar Publisher (C++)
 * 
 * This application simulates a radar sensor that publishes object detections.
 * Pattern: Pure Publisher - sends events periodically, no RPC handling.
 * 
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Fusion Hawking Contributors
 */

#include <iostream>
#include <vector>
#include <thread>
#include <chrono>
#include <cmath>
#include <random>
#include <memory>
#include <atomic>

#include <fusion_hawking/runtime.hpp>
#include "bindings.h"  // Generated bindings

using namespace fusion_hawking;
using namespace generated;

// --- Radar Service Implementation ---
class RadarServiceImpl : public RadarServiceStub {
public:
    RadarServiceImpl(SomeIpRuntime* rt, std::shared_ptr<ILogger> log)
        : runtime(rt), logger(log), total_detections(0) {}

    // Field getter
    virtual int32_t GetDetectionCount() override {
        return total_detections;
    }

    // Simulate radar scan and publish detections
    void SimulateScan() {
        static std::mt19937 rng(42);
        static std::uniform_real_distribution<float> range_dist(5.0f, 150.0f);
        static std::uniform_real_distribution<float> vel_dist(-30.0f, 10.0f);
        static std::uniform_real_distribution<float> angle_dist(-45.0f, 45.0f);
        static std::uniform_int_distribution<int> count_dist(1, 5);

        int num_objects = count_dist(rng);
        std::vector<RadarObject> objects;

        for (int i = 0; i < num_objects; ++i) {
            RadarObject obj;
            obj.id = total_detections + i;
            obj.range_m = range_dist(rng);
            obj.velocity_mps = vel_dist(rng);
            obj.azimuth_deg = angle_dist(rng);
            objects.push_back(obj);
        }

        total_detections += num_objects;

        // Publish the event
        RadarServiceOnObjectDetectedEvent evt;
        evt.objects = objects;

        if (logger) {
            logger->Log(LogLevel::INFO, "RadarService", 
                "Publishing " + std::to_string(num_objects) + " objects (total: " + 
                std::to_string(total_detections) + ")");
        }

        runtime->SendNotification(SERVICE_ID, EVENT_ON_OBJECT_DETECTED, evt.serialize());
    }

private:
    SomeIpRuntime* runtime;
    std::shared_ptr<ILogger> logger;
    int32_t total_detections;
};


int main() {
    auto logger = std::make_shared<ConsoleLogger>();
    logger->Log(LogLevel::INFO, "Main", "=== Radar Publisher Demo (C++) ===");
    logger->Log(LogLevel::INFO, "Main", "Simulating radar sensor, publishing detections...");

    SomeIpRuntime rt("examples/automotive_pubsub/config.json", "radar_cpp_instance", logger);

    RadarServiceImpl radar_svc(&rt, logger);
    rt.offer_service("radar-service", &radar_svc);

    logger->Log(LogLevel::INFO, "Main", "RadarService offered. Starting event loop.");

    std::atomic<bool> running(true);

    // Publish radar detections every 100ms (10 Hz)
    while (running) {
        radar_svc.SimulateScan();
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    return 0;
}
