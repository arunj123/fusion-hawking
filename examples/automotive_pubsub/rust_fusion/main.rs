//! Automotive Pub-Sub Demo: Fusion Node (Rust)
//!
//! This application subscribes to RadarService events, performs sensor fusion,
//! and publishes fused track updates.
//! 
//! Pattern: Subscriber + Publisher
//!
//! SPDX-License-Identifier: MIT
//! Copyright (c) 2026 Fusion Hawking Contributors

use fusion_hawking::runtime::SomeIpRuntime;
use fusion_hawking::logging::LogLevel;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

pub mod generated {
    include!(concat!(env!("CARGO_MANIFEST_DIR"), "/build/generated/rust/mod.rs"));
}

use generated::{
    FusionServiceProvider, FusionServiceServer,
    RadarServiceClient, FusedTrack,
};

// --- Fusion Service Implementation ---
struct FusionImpl {
    logger: Arc<dyn fusion_hawking::logging::FusionLogger>,
    active_tracks: std::sync::Mutex<Vec<FusedTrack>>,
}

impl FusionImpl {
    fn new(logger: Arc<dyn fusion_hawking::logging::FusionLogger>) -> Self {
        FusionImpl {
            logger,
            active_tracks: std::sync::Mutex::new(Vec::new()),
        }
    }

    /// Process incoming radar objects and update tracks
    fn process_radar_data(&self, _objects: Vec<generated::RadarObject>) {
        // Simple fusion: convert radar polar to cartesian
        let mut tracks = self.active_tracks.lock().unwrap();
        tracks.clear();

        // Mock fusion logic - in real system this would be Kalman filter etc.
        for (i, _obj) in _objects.iter().enumerate() {
            let track = FusedTrack {
                track_id: i as i32,
                position_x: _obj.range_m * _obj.azimuth_deg.to_radians().cos(),
                position_y: _obj.range_m * _obj.azimuth_deg.to_radians().sin(),
                velocity_x: _obj.velocity_mps * _obj.azimuth_deg.to_radians().cos(),
                velocity_y: _obj.velocity_mps * _obj.azimuth_deg.to_radians().sin(),
                confidence: 0.85,
            };
            tracks.push(track);
        }

        self.logger.log(
            LogLevel::Info,
            "FusionService",
            &format!("Fused {} tracks from radar data", tracks.len()),
        );
    }
}

impl FusionServiceProvider for FusionImpl {
    fn get_active_tracks(&self) -> Vec<FusedTrack> {
        self.active_tracks.lock().unwrap().clone()
    }

    fn reset_tracks(&self) -> bool {
        self.active_tracks.lock().unwrap().clear();
        self.logger.log(LogLevel::Info, "FusionService", "Tracks cleared");
        true
    }
}

fn main() {
    let rt = SomeIpRuntime::load("examples/automotive_pubsub/config.json", "fusion_rust_instance");
    let logger = rt.get_logger();
    
    logger.log(LogLevel::Info, "Main", "=== Fusion Node Demo (Rust) ===");
    logger.log(LogLevel::Info, "Main", "Subscribing to RadarService, publishing FusedTracks...");

    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    let l = logger.clone();
    
    ctrlc::set_handler(move || {
        l.log(LogLevel::Info, "Main", "Shutting down...");
        r.store(false, Ordering::SeqCst);
    }).ok();

    // Offer FusionService
    let fusion_impl = Arc::new(FusionImpl::new(logger.clone()));
    let fusion = FusionServiceServer::new(fusion_impl.clone());
    rt.offer_service("fusion-service", Box::new(fusion));

    // Subscribe to RadarService events
    rt.subscribe_eventgroup(
        RadarServiceClient::SERVICE_ID,
        1,  // instance_id
        1,  // eventgroup_id
        100 // TTL
    );

    logger.log(LogLevel::Info, "Main", "FusionService offered. Waiting for radar events...");

    // Start runtime in background
    let rt_clone = rt.clone();
    thread::spawn(move || rt_clone.run());

    // Main loop - publish fused tracks periodically
    while running.load(Ordering::Relaxed) {
        // In a real implementation, this would be triggered by radar events
        // For demo, we simulate processing
        let tracks = fusion_impl.get_active_tracks();
        if !tracks.is_empty() {
            // Would call: rt.send_notification(FusionService::SERVICE_ID, EVENT_ON_TRACK_UPDATED, ...)
            logger.log(
                LogLevel::Info,
                "FusionService",
                &format!("Publishing {} fused tracks", tracks.len()),
            );
        }
        
        thread::sleep(Duration::from_millis(200));
    }

    rt.stop();
}
