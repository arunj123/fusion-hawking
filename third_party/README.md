# Third Party Libraries

This directory contains external libraries used by the Fusion Hawking project for interoperability testing and extended functionality.

## Included Libraries

### someipy
- **Repository**: [https://github.com/chrizog/someipy](https://github.com/chrizog/someipy)
- **Purpose**: Provides a standard-compliant Python SOME/IP implementation.
- **Usage**: Used in `examples/someipy_demo` to demonstrate interoperability with external SOME/IP stacks.
- **Windows Support**: Note that this library is primarily developed for Linux. We use runtime monkey-patching in our example scripts to handle Windows-specific socket behaviors (like loopback multicast binding) without modifying the submodule source code itself.

## Strategy for Third-Party Code
- **Submodules**: Libraries are included as git submodules to maintain a clear boundary and facilitate updates from upstream.
- **Non-Invasive**: We avoid patching the source code of third-party libraries directly whenever possible. Instead, we use configuration, environment variables, or runtime patching (monkey-patching) to adapt them to our needs.
