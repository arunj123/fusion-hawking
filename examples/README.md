# Fusion Hawking Examples

This directory contains examples demonstrating how to use the `fusion-hawking` SOME/IP stack. The examples are categorized into four levels of complexity.

## Directory Structure

```
examples/
├── sd_demos/           # 1. Raw Service Discovery Logic
├── simple_no_sd/       # 2. Minimal Wire-Protocol (No SD)
│   ├── rust/
│   ├── python/
│   └── cpp/
├── integrated_apps/    # 3. Full Runtime Integration (RPC)
│   ├── rust_app/
│   ├── python_app/
│   └── cpp_app/
└── automotive_pubsub/         # 4. Automotive Pub-Sub Pattern
    ├── cpp_radar/      # Publisher (C++)
    ├── rust_fusion/    # Subscriber + Publisher (Rust)
    └── python_adas/    # Subscriber (Python)
```

---

## 1. Raw Service Discovery (`sd_demos/`)
**Purpose**: To demonstrate the Service Discovery State Machine in isolation.
- `sd_demo.rs`: A single Rust binary that spawns a **Provider** thread and a **Consumer** thread. They discover each other via Multicast UDP (`224.0.0.1:30490`).

![SD Demo Sequence](../docs/images/sd_demo_sequence.png)

<details>
<summary>View PlantUML Source</summary>

[sd_demo_sequence.puml](../docs/diagrams/sd_demo_sequence.puml)
</details>
---

## 2. Simple No-SD (`simple_no_sd/`)
**Purpose**: To demonstrate the "Under the Hood" wire protocol **without** the complexity of the Runtime or Service Discovery.
These examples manually construct the **16-byte SOME/IP Header** and send raw UDP packets to fixed ports (Localhost).

- **Rust**: `rust/server.rs` (Port 40000) & `rust/client.rs`
- **Python**: `python/server.py` (Port 40001) & `python/client.py`
- **C++**: `cpp/server.cpp` (Port 40002) & `cpp/client.cpp`

**Key Concepts**:
- Manually packing bytes (Big Endian).
- Handling Request (0x00) and Response (0x80) Message Types.
- No config files, no discovery delays.

![Simple No-SD Sequence](../docs/images/simple_no_sd_sequence.png)

<details>
<summary>View PlantUML Source</summary>

[simple_no_sd_sequence.puml](../docs/diagrams/simple_no_sd_sequence.puml)
</details>
---

## 3. Integrated Apps (`integrated_apps/`)
**Purpose**: To demonstrate the full **Production-Ready** usage of the library.
These apps use the `SomeIpRuntime`, which handles:
- **Configuration Loading** (`config.json`).
- **Service Discovery** (Auto-discovery of peers).
- **Code Generation** (Typed Interfaces).

### Configuration (`config.json`)
The `config.json` defines the network topology.
```json
{
  "instances": {
    "rust_app_instance": { "ip": "127.0.0.1", "providing": { ... } },
    "python_app_instance": { "required": { "math-service": { ... } } }
  }
}
```

### Code Generation
To develop these apps, we first generate bindings from an IDL using the `codegen` tool.

**Usage**:
```bash
# Generate Rust Bindings
cargo run --bin codegen -- --idl interface.json --lang rust --out src/generated

# Generate Python Bindings
cargo run --bin codegen -- --idl interface.json --lang python --out src/python/generated
```

**Architecture**:

![Integrated Apps Interaction](../docs/images/integrated_apps_interaction.png)

<details>
<summary>View PlantUML Source</summary>

[integrated_apps_interaction.puml](../docs/diagrams/integrated_apps_interaction.puml)
</details>
---

## 4. Automotive Pub-Sub (`automotive_pubsub/`)
**Purpose**: To demonstrate the **publish-subscribe** pattern using SOME/IP events, inspired by automotive middleware patterns.

This example shows a realistic automotive data flow:
- **RadarService** (C++): Publishes radar object detections at 10Hz
- **FusionService** (Rust): Subscribes to radar, publishes fused tracks
- **ADAS App** (Python): Subscribes to fusion events, logs warnings

**Key APIs**:
- `@event` decorator for defining events in IDL
- `subscribe_eventgroup()` to subscribe to events
- `SendNotification()` to publish events

See [automotive_pubsub/README.md](automotive_pubsub/README.md) for detailed instructions.

---

## Previewing Diagrams
To view the PlantUML diagrams in VS Code:
1. Install the **PlantUML** extension (by Jebbs).
2. Open this file.
3. Press `Alt+D` to toggle the preview.
