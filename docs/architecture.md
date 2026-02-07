# Fusion Hawking Architecture

> **See Also:** [User Guide](user_guide.md) | [IDL Reference](IDL.md) | [Design Doc](design_and_requirements.md) | [Test Matrix](test_matrix.md)

This document provides a comprehensive view of the Fusion Hawking SOME/IP stack architecture, including deployment topology, internal layers, data flows, and component interactions.

---

## High-Level System Overview

Fusion Hawking is a **lightweight, dependency-free SOME/IP library** implemented primarily in Rust, with native bindings for Python and C++. The stack adheres to the AUTOSAR SOME/IP and SOME/IP-SD protocol specifications.

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam componentStyle rectangle

package "Fusion Hawking Stack" {
    [Rust Core Library] as Core
    [Python Runtime] as PyRT
    [C++ Runtime] as CppRT
    [Code Generator (IDL)] as Codegen
    [Automation Toolkit] as Fusion
}

package "Application Layer" {
    [Rust Application] as RustApp
    [Python Application] as PyApp
    [C++ Application] as CppApp
}

package "Network Layer" {
    [UDP Transport] as UDP
    [TCP Transport] as TCP
    [Multicast (SD)] as Mcast
}

RustApp --> Core
PyApp --> PyRT
CppApp --> CppRT
PyRT ..> Core : "Same Protocol"
CppRT ..> Core : "Same Protocol"

Core --> UDP
Core --> TCP
Core --> Mcast

Codegen --> RustApp : generates
Codegen --> PyApp : generates
Codegen --> CppApp : generates
Fusion --> Core : builds & tests

@enduml
```

---

## Deployment Topology

Applications can be deployed anywhere on the network. Service Discovery enables dynamic peer detection across hosts. Configuration-driven deployment allows runtime port binding without recompilation.

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

node "Host A: Rust Server" as HostA {
    artifact "rust_app" as RA
    database "config.json" as CfgA
    RA --> CfgA : loads
}

node "Host B: Python Client" as HostB {
    artifact "python_app" as PA
    database "config.json" as CfgB
    PA --> CfgB : loads
}

node "Host C: C++ Client" as HostC {
    artifact "cpp_app" as CA
    database "config.json" as CfgC
    CA --> CfgC : loads
}

cloud "Network" as Net {
    interface "UDP Unicast\n(Service Communication)" as Unicast
    interface "UDP Multicast\n224.0.0.1:30490\n(Service Discovery)" as Multicast
}

RA -down-> Unicast : bind port 30509
PA -down-> Unicast : request
CA -down-> Unicast : request

RA --> Multicast : Offer Service
PA --> Multicast : Find Service
CA --> Multicast : Subscribe EventGroup

@enduml
```

> **Configuration Schema:** See [Design Doc - JSON Configuration](design_and_requirements.md#2-json-configuration-schema)

---

## Layered Architecture

The stack follows a clean layered architecture with strict separation of concerns:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam rectangleBorderColor #333
skinparam rectangleBackgroundColor #E8F4FD

package "Application Layer" #F5F5F5 {
    rectangle "Generated Service Stubs\n(MathServiceServer, StringServiceClient)" as GenCode
    rectangle "User Business Logic" as UserLogic
}

package "Runtime Layer" #E8F4FD {
    rectangle "SomeIpRuntime\n- Config Loading\n- Service Lifecycle\n- Request Dispatching" as Runtime
    rectangle "ThreadPool\n- Concurrent Handler Execution\n- Non-blocking IO" as Pool
}

package "Service Discovery Layer" #D4EDDA {
    rectangle "ServiceDiscovery\n- State Machine (Down→InitialWait→Repetition→Main)\n- TTL Management\n- EventGroup Subscriptions" as SD
    rectangle "LocalService / RemoteService\n- Offer/Find/Subscribe" as SvcState
}

package "Codec Layer" #FFF3CD {
    rectangle "SomeIpHeader\n- 16-byte Header Parsing/Serialization\n- MessageType, ReturnCode" as Header
    rectangle "Serialization Traits\n- SomeIpSerialize / SomeIpDeserialize\n- Complex Types (Arrays, Structs)" as Serialize
    rectangle "Session Management\n- Per-Service Session Counter" as Session
}

package "Transport Layer" #F8D7DA {
    rectangle "UdpTransport\n- Unicast + Multicast\n- Non-blocking IO" as UdpT
    rectangle "TcpTransport\n- Connection Management\n- Stream Handling" as TcpT
    rectangle "SomeIpTransport Trait\n- Unified Interface" as Trait
}

UserLogic --> GenCode
GenCode --> Runtime
Runtime --> Pool
Runtime --> SD
SD --> SvcState
Runtime --> Header
SD --> Header
Header --> Serialize
Serialize --> Session
SD --> UdpT
Runtime --> UdpT
Runtime --> TcpT
UdpT --|> Trait
TcpT --|> Trait

@enduml
```

---

## Request/Response Data Flow

This diagram shows the complete data flow for an RPC call from a Python client to a Rust server:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

actor "Python Client" as Client
participant "Python Runtime\n(SomeIpRuntime)" as PyRT
participant "Codec Layer\n(Header build)" as PyCodec
participant "UDP Transport" as Net
participant "Rust Runtime\n(SomeIpRuntime)" as RsRT
participant "Dispatcher" as Disp
participant "MathServiceImpl\n(User Code)" as Impl

Client -> PyRT: client.add(5, 3)

group Request Path
    PyRT -> PyCodec: Build Header\n(ServiceID=0x1234, MethodID=0x0001,\nMsgType=REQUEST)
    PyCodec -> PyCodec: Serialize payload (5, 3)
    PyCodec -> Net: UDP Send
    Net -> RsRT: recv_from()
    RsRT -> RsRT: Parse Header
    RsRT -> Disp: Lookup handler\n(ServiceID=0x1234)
    Disp -> Impl: handle(method=1, payload)
    Impl -> Impl: Compute 5+3=8
end

group Response Path
    Impl --> Disp: return (8)
    Disp --> RsRT: Build Response\n(MsgType=RESPONSE)
    RsRT --> Net: UDP Send
    Net --> PyRT: recv_from()
    PyRT --> PyRT: Parse Response
    PyRT --> Client: return 8
end

@enduml
```

> **API Usage:** See [User Guide - Runtime API](user_guide.md#runtime-api)

---

## Service Discovery State Machine

The SD layer implements the AUTOSAR-specified state machine for service lifecycle per [PRS_SOMEIPSD_00011-00014]:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

[*] --> Down

Down --> InitialWait : offer_service()
note right of InitialWait
  [PRS_SOMEIPSD_00012]
  Random delay:
  INITIAL_DELAY_MIN..INITIAL_DELAY_MAX
end note

InitialWait --> Repetition : delay_elapsed
note right of Repetition
  [PRS_SOMEIPSD_00013]
  Send Offers exponentially:
  REPETITIONS_BASE_DELAY * 2^n
end note

Repetition --> Main : repetitions_done
note right of Main
  [PRS_SOMEIPSD_00014]
  Steady state:
  Send periodic Offers
  (CYCLIC_OFFER_DELAY)
end note

Main --> Down : stop_offer()
Repetition --> Down : stop_offer()
InitialWait --> Down : stop_offer()

@enduml
```

---

## Subscription Flow

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

participant "Consumer\n(Python)" as Consumer
participant "Multicast\n(224.0.0.1:30490)" as MC
participant "Provider\n(Rust)" as Provider

== Discovery ==
Provider -> MC: OfferService\n(ServiceID, InstanceID, Port, TTL)
MC -> Consumer: Forward Offer
Consumer -> Consumer: Update remote_services[]

== Subscription ==
Consumer -> MC: SubscribeEventgroup\n(ServiceID, EventgroupID, TTL)
MC -> Provider: Forward Subscribe
Provider -> Provider: Add to subscribers[]
Provider -> MC: SubscribeEventgroupAck
MC -> Consumer: Forward Ack
Consumer -> Consumer: subscription_acked = true

== Events ==
loop Every 100ms
    Provider -> Consumer: Notification Event\n(MSGTYPE=0x02)
    Consumer -> Consumer: on_event(data)
end

@enduml
```

> **Event Definitions:** See [IDL - Events](IDL.md#events-pubsub)

---

## SOME/IP Message Format

The 16-byte header structure per AUTOSAR PRS_SOMEIP:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE
skinparam rectangleBackgroundColor #E8F4FD

rectangle "SOME/IP Header (16 bytes)" {
    rectangle "Bytes 0-1\n**Service ID**" as SID #FFE6CC
    rectangle "Bytes 2-3\n**Method ID**" as MID #FFE6CC
    rectangle "Bytes 4-7\n**Length**\n(Payload + 8)" as LEN #D5E8D4
    rectangle "Bytes 8-9\n**Client ID**" as CID #DAE8FC
    rectangle "Bytes 10-11\n**Session ID**" as SESS #DAE8FC
    rectangle "Byte 12\n**Protocol Ver**\n(0x01)" as PVER #E1D5E7
    rectangle "Byte 13\n**Interface Ver**" as IVER #E1D5E7
    rectangle "Byte 14\n**Message Type**" as MTYPE #F8CECC
    rectangle "Byte 15\n**Return Code**" as RCODE #F8CECC
}

SID -right-> MID
MID -right-> LEN
LEN -down-> CID
CID -right-> SESS
SESS -right-> PVER
PVER -right-> IVER
IVER -right-> MTYPE
MTYPE -right-> RCODE

note bottom of MTYPE
  0x00 = REQUEST
  0x01 = REQUEST_NO_RETURN
  0x02 = NOTIFICATION
  0x80 = RESPONSE
  0x81 = ERROR
end note

@enduml
```

> **Serialization Details:** See [IDL - Serialization](IDL.md#serialization-details)

---

## Code Generation Pipeline

The IDL compiler generates type-safe bindings for all supported languages:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

file "interface.py\n(Python dataclasses)" as IDL
component "tools/codegen/parser.py\n- Extract types, methods, events" as Parser
component "tools/codegen/generators/\n- rust.py\n- python.py\n- cpp.py" as Generators

artifact "build/generated/rust/\n*.rs" as RustGen
artifact "build/generated/python/\n*.py" as PyGen
artifact "build/generated/cpp/\n*.hpp" as CppGen

IDL --> Parser
Parser --> Generators
Generators --> RustGen
Generators --> PyGen
Generators --> CppGen

note bottom of IDL
  @dataclass
  class MathService:
      @method(id=1)
      def add(a: int, b: int) -> int: ...
      
      @event(id=0x8001)
      on_result: int
end note

@enduml
```

> **Full IDL Reference:** See [IDL Documentation](IDL.md)

---

## Cross-Language Runtime Architecture

Each language runtime provides the same API semantics:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

package "Rust Runtime (src/runtime/)" #FFE6CC {
    class SomeIpRuntime {
        +load(config, instance): Arc<Self>
        +offer_service(alias, handler)
        +get_client<T>(alias): T
        +run()
        +stop()
    }
    class ServiceDiscovery
    class ThreadPool
    SomeIpRuntime --> ServiceDiscovery
    SomeIpRuntime --> ThreadPool
}

package "Python Runtime (src/python/)" #D4EDDA {
    class SomeIpRuntime as PyRuntime {
        +__init__(config, instance)
        +offer_service(alias, handler)
        +get_client(alias, cls)
        +start() / stop()
    }
    class SessionIdManager
    PyRuntime --> SessionIdManager
}

package "C++ Runtime (src/cpp/)" #DAE8FC {
    class SomeIpRuntime as CppRuntime {
        +SomeIpRuntime(config, instance)
        +offer_service(alias, impl)
        +create_client<T>(alias)
        +run()
    }
    class JsonConfig
    CppRuntime --> JsonConfig
}

note "All runtimes share:\n- Config-driven topology\n- Same wire protocol\n- Same SD multicast group" as N
N .. SomeIpRuntime
N .. PyRuntime
N .. CppRuntime

@enduml
```

> **Logging Interface:** See [Design Doc - Logging](design_and_requirements.md#3-logging-abstraction-dlt-ready)

---

## Automation & CI/CD Pipeline

The `tools/fusion/` toolkit orchestrates the complete build/test/coverage workflow:

```plantuml
@startuml
skinparam backgroundColor #FEFEFE

start

partition "Toolchain Check" {
    :toolchains.py;
    note right: Verify Rust, CMake,\nPython, llvm-cov
}

partition "Build Phase" {
    :build.py;
    split
        :cargo build (Rust);
    split again
        :cmake build (C++);
    split again
        :codegen (all bindings);
    end split
}

partition "Test Phase" {
    :test.py;
    split
        :cargo test;
    split again
        :pytest;
    split again
        :ctest;
    end split
    :Integration Demo;
    note right: Multi-process\ncross-language RPC
}

partition "Coverage" {
    :coverage.py;
    split
        :cargo-llvm-cov (Rust);
    split again
        :coverage.py (Python);
    split again
        :OpenCppCoverage (C++);
    end split
}

partition "Reporting" {
    :report.py;
    :Generate HTML Dashboard;
    :server.py;
    note right: Serve @ localhost:8000
}

stop

@enduml
```

> **Coverage Reports:** See [Test Matrix - Coverage](test_matrix.md#coverage-reports)

---

## Module Reference

| Module | Path | Description | Docs |
|--------|------|-------------|------|
| **Codec** | `src/codec/` | Header parsing, serialization traits | [IDL](IDL.md#serialization-details) |
| **Transport** | `src/transport/` | UDP/TCP abstraction with multicast | |
| **Service Discovery** | `src/sd/` | AUTOSAR-compliant SD state machine | |
| **Runtime** | `src/runtime/` | High-level API for service lifecycle | [User Guide](user_guide.md#runtime-api) |
| **Logging** | `src/logging.rs` | DLT-ready logger abstraction | [Design Doc](design_and_requirements.md#3-logging-abstraction-dlt-ready) |
| **Python Bindings** | `src/python/` | Native Python runtime | |
| **C++ Bindings** | `src/cpp/` | Modern C++14 runtime | |
| **Code Generator** | `tools/codegen/` | IDL compiler for multi-language stubs | [IDL](IDL.md) |
| **Automation** | `tools/fusion/` | Build, test, coverage, dashboard | |

---

## References

- [AUTOSAR SOME/IP Protocol Specification](../AUTOSAR_PRS_SOMEIPProtocol.pdf)
- [AUTOSAR SOME/IP-SD Protocol Specification](../AUTOSAR_PRS_SOMEIPServiceDiscoveryProtocol.pdf)
- [Examples README](../examples/README.md)
