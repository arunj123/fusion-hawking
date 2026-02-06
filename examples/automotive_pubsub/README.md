# Automotive Publish-Subscribe Demo

This example demonstrates the **publish-subscribe** communication pattern using SOME/IP events, inspired by automotive middleware patterns.

> **Disclaimer**: This is an independent, open-source implementation demonstrating common automotive communication patterns. It is not affiliated with, endorsed by, or derived from any proprietary automotive standard or specification. All code is original work licensed under MIT.

## License

SPDX-License-Identifier: MIT

## Architecture Overview

This demo simulates a realistic autonomous driving perception pipeline:

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   RadarService  │       │ FusionService   │       │   ADAS App      │
│     (C++)       │──────▶│     (Rust)      │──────▶│    (Python)     │
│   [Publisher]   │ Event │ [Sub + Pub]     │ Event │  [Subscriber]   │
└─────────────────┘       └─────────────────┘       └─────────────────┘
     Port 30601                Port 30602
```

**Data Flow:**
1. **RadarService** (C++): Simulates radar sensor, publishes `on_object_detected` events at 10Hz
2. **FusionService** (Rust): Subscribes to radar events, fuses data, publishes `on_track_updated`
3. **ADAS App** (Python): Subscribes to fusion events, logs collision warnings

---

## Design: SOME/IP Event Architecture

```plantuml
@startuml
skinparam componentStyle uml2
skinparam backgroundColor #FEFEFE

package "ECU 1 - Radar Sensor" {
    [RadarServiceImpl] as RS
    note bottom of RS : Publishes at 10Hz
}

package "ECU 2 - Fusion Controller" {
    [FusionServiceImpl] as FS
    note bottom of FS : Subscribes + Publishes
}

package "ECU 3 - ADAS Domain Controller" {
    [AdasApplication] as AA
    note bottom of AA : Pure Subscriber
}

cloud "SOME/IP Network" as NET {
    [Service Discovery\n(Multicast 224.0.0.1:30490)] as SD
}

RS -down-> SD : Offer RadarService
FS -down-> SD : Find RadarService\nOffer FusionService
AA -down-> SD : Find FusionService

RS =right=> FS : **on_object_detected**\n(EventGroup 1)
FS =right=> AA : **on_track_updated**\n(EventGroup 1)

@enduml
```

---

## Sequence Diagram: Event Flow

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam sequenceArrowThickness 2

participant "RadarService\n(C++)" as R #FFB3B3
participant "FusionService\n(Rust)" as F #B3D9FF
participant "ADAS App\n(Python)" as A #B3FFB3

== Initialization ==
R -> R : offer_service("radar-service")
F -> R : subscribe_eventgroup(0x7001, 1)
F -> F : offer_service("fusion-service")
A -> F : subscribe_eventgroup(0x7002, 1)

== Runtime Event Loop ==
loop Every 100ms
    R -> R : SimulateScan()
    R ->> F : **on_object_detected**(RadarObject[])
    note right of R : SOME/IP Event\nType: 0x02
    
    F -> F : ProcessRadarData()
    F -> F : UpdateTracks()
    F ->> A : **on_track_updated**(FusedTrack[])
    
    A -> A : CheckCollisionWarning()
    alt distance < 10m
        A -> A : Log Warning
    end
end

@enduml
```

---

## Data Types

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam classAttributeIconSize 0

class RadarObject {
    +id: int
    +range_m: float
    +velocity_mps: float
    +azimuth_deg: float
}

class FusedTrack {
    +track_id: int
    +position_x: float
    +position_y: float
    +velocity_x: float
    +velocity_y: float
    +confidence: float
}

class RadarService <<service 0x7001>> {
    +on_object_detected(objects: RadarObject[])
    +detection_count: int <<field>>
}

class FusionService <<service 0x7002>> {
    +on_track_updated(tracks: FusedTrack[])
    +get_active_tracks(): FusedTrack[]
    +reset_tracks(): bool
}

RadarService ..> RadarObject : publishes
FusionService ..> FusedTrack : publishes
FusionService ..> RadarObject : subscribes to

@enduml
```

---

## Key APIs Demonstrated

| API | Language | Purpose |
|-----|----------|---------|
| `SendNotification()` | C++ | Publish an event to subscribers |
| `subscribe_eventgroup()` | Rust/Python | Subscribe to an event group |
| `unsubscribe_eventgroup()` | Rust/Python | Unsubscribe from events |
| `@event` decorator | Python IDL | Define an event in the interface |
| `@field` decorator | Python IDL | Define a field with notifier |

---

## Automotive Communication Concepts

| Concept | SOME/IP Equivalent |
|--------------------|--------------------|
| **Sender/Receiver** | Service with Events |
| **Message (PDU)** | SOME/IP Message Payload |
| **Signal** | Event Data (serialized struct) |
| **Event Subscription** | `subscribe_eventgroup()` |
| **Event Notification** | SOME/IP Event Message (Type 0x02) |
| **Event Group** | Collection of related events |

---

## Running the Demo

### 1. Generate Bindings
```bash
# Generate bindings for all languages
python -m tools.codegen.main --idl examples/automotive_pubsub/interface.py --all
```

### 2. Build
```bash
# Build Rust
cargo build --release

# Build C++
cmake --build build --target radar_demo
```

### 3. Run (3 terminals)

**Terminal 1 - Radar (C++):**
```bash
.\build\radar_demo.exe
```

**Terminal 2 - Fusion (Rust):**
```bash
cargo run --bin fusion_node
```

**Terminal 3 - ADAS (Python):**
```bash
python examples/automotive_pubsub/python_adas/main.py
```

### 4. Automated (via fusion.bat)
```bash
.\fusion.bat
```
The demo is automatically run as part of the integration test suite.

---

## Expected Output

**Radar (C++):**
```
=== Radar Publisher Demo (C++) ===
[INFO] RadarService: Publishing 3 objects (total: 3)
[INFO] RadarService: Publishing 4 objects (total: 7)
```

**Fusion (Rust):**
```
=== Fusion Node Demo (Rust) ===
[INFO] FusionService: Fused 3 tracks from radar data
[INFO] FusionService: Publishing 3 fused tracks
```

**ADAS (Python):**
```
=== ADAS Application Demo (Python) ===
[INFO] ADAS: Received 3 fused tracks (total: 3)
[WARN] ADAS: ** COLLISION WARNING: Track 0 at 8.5m! **
```

---

## Files

| File | Description |
|------|-------------|
| `interface.py` | Service definitions (RadarService, FusionService) |
| `config.json` | Network configuration for all 3 nodes |
| `cpp_radar/main.cpp` | C++ radar publisher |
| `rust_fusion/main.rs` | Rust fusion node (sub + pub) |
| `python_adas/main.py` | Python ADAS subscriber |

## Previewing Diagrams

To view the PlantUML diagrams in VS Code:
1. Install the **PlantUML** extension (by Jebbs).
2. Open this file.
3. Press `Alt+D` to toggle the preview.
