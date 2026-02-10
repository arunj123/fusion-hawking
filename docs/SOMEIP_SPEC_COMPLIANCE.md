# SOME/IP Specification Compliance

This document outlines the specific versions and interpretations of the SOME/IP and SOME/IP-SD protocols implemented in the Fusion Hawking project.

## Referenced Specifications

The implementation is based on the **AUTOSAR R22-11** release and is verified against the following official specifications:

*   **SOME/IP Protocol**: [AUTOSAR_PRS_SOMEIPProtocol.pdf (R22-11)](https://www.autosar.org/fileadmin/standards/R22-11/FO/AUTOSAR_PRS_SOMEIPProtocol.pdf)
*   **Service Discovery**: [AUTOSAR_PRS_SOMEIPServiceDiscoveryProtocol.pdf (R22-11)](https://www.autosar.org/fileadmin/standards/R22-11/FO/AUTOSAR_PRS_SOMEIPServiceDiscoveryProtocol.pdf)

## Protocol Versions

| Protocol | Version | Constant | Description |
| :--- | :--- | :--- | :--- |
| **SOME/IP Protocol** | 0x01 | `PROTOCOL_VERSION` | Version of the SOME/IP header format. |
| **Interface Version** | 0x01 | `INTERFACE_VERSION` | Default interface version for services. |
| **Service Discovery**| 0x01 | `PROTOCOL_VERSION_SD`| Version of the SD message format. |

## SD Option Lengths (R22-11 Compliance)

As per **[PRS_SOMEIPSD_00280]** (R22-11):
> The Length field shall contain the length of the option in Bytes. This includes the ... **Type field** and the Reserved field... The Length field excludes the Length field itself.

Based on this, the following lengths are enforced across all runtimes (Python, C++, Rust):

*   **IPv4 Endpoint Option**: `0x000A` (10) bytes
    *   (1 byte Type + 1 byte Reserved + 4 bytes IP + 1 byte Reserved + 1 byte Proto + 2 bytes Port)
*   **IPv6 Endpoint Option**: `0x0016` (22) bytes
    *   (1 byte Type + 1 byte Reserved + 16 bytes IP + 1 byte Reserved + 1 byte Proto + 2 bytes Port)

## Implementation Status

*   **Python**: Verified with `someipy` (standard compliance).
*   **C++**: Enforced in `runtime.cpp`.
*   **Rust**: Enforced in `src/sd/options.rs`.

## Platform Support

The Fusion Hawking runtimes and the `someipy` reference library are tested and supported on the following platforms:

*   **Ubuntu 22.04+**: Primary development and CI environment.
*   **Windows 10/11**: Fully supported for all runtimes. Note that `someipy` requires specific socket patches (included in our fork) for reliable multicast and loopback communication on Windows.

Regression tests ("Golden Byte" tests) have been added to ensure these lengths are never accidentally changed.
