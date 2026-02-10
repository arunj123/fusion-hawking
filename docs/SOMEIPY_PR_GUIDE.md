# PR Guide: someipy Standard Compliance & Windows Multicast

This guide documents the changes made to the `someipy` library to align with the SOME/IP SD specification and ensure reliability on Windows. Use this information to create a formal Pull Request to the upstream repository.

## 1. SD Option Length Correction
**Problem**: The IPv4 and IPv6 Endpoint Option lengths were set to 9 and 21 respectively.
**Requirement**: According to the SOME/IP SD specification (e.g., [PRS_SOMEIPSD_00280]), the Length field MUST include the Type field.
**Fix**: Updated lengths to 10 (IPv4) and 22 (IPv6).

### Changes in `someipy/_internal/_sd/deserialization/sd_serialization.py`:
```python
# IPv4 Endpoint Option
LENGTH = 0x000A  # Changed from 0x0009

# IPv6 Endpoint Option
LENGTH = 0x0016  # Changed from 0x0015
```

## 2. SD Deserialization Pointer Correction
**Problem**: Deserialization was failing because it didn't account for the Type field being included in the Length.
**Fix**: Adjusted the pointer arithmetic to correctly skip the Option header and payload.

### Changes in `someipy/_internal/_sd/deserialization/sd_deserialization.py`:
```python
# Bytes to skip = Length + 2 (the size of the Length field itself)
bytes_options_left -= common_option_data.option_length + 2
current_pos_option += common_option_data.option_length + 2
```

## 3. Windows Multicast Socket Fix
**Problem**: Multicast socket creation on Windows often requires `SO_REUSEADDR` to be set *before* binding, and binding to the wildcard address (`""`) rather than the multicast IP for receiving.
**Fix**: Unconditionally set `SO_REUSEADDR` and apply Windows-specific binding logic.

### Changes in `someipy/_internal/utils.py`:
```python
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
if platform.system() == "Windows":
    sock.bind(("", port))
else:
    sock.bind((ip_address, port))
```

## 4. Verification
Passes `tests/test_someipy_wire_format.py` (external test suite) ensuring:
1. Wire format contains Length 10/22.
2. SD Offers are correctly advertised on the network.
3. Multicast works reliably on Windows 10/11.
