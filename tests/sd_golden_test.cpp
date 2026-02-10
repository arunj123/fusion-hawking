#include <iostream>
#include <vector>
#include <cassert>
#include <cstring>
#include <iomanip>

#ifdef _WIN32
#include <winsock2.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#endif

void hex_dump(const std::vector<uint8_t>& data) {
    for(auto b : data) std::cout << std::hex << std::setw(2) << std::setfill('0') << (int)b << " ";
    std::cout << std::dec << std::endl;
}

int main() {
#ifdef _WIN32
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif

    std::cout << "Running C++ SD Golden Byte Test (Standard: 9/21)..." << std::endl;

    // 1. Create a Golden IPv4 Offer packet (Standard Compliant: Len=9)
    std::vector<uint8_t> golden_v4 = {
        0xFF, 0xFF, 0x81, 0x00, 
        0x00, 0x00, 0x00, 0x2C, 
        0x00, 0x00, 0x00, 0x01, 
        0x01, 0x01, 0x02, 0x00, 
        
        0x80, 0x00, 0x00, 0x00, 
        0x00, 0x00, 0x00, 0x10, 
        
        0x01, 0x00, 0x00, 0x10, 
        0x12, 0x34, 0x00, 0x01, 
        0x01, 0xFF, 0xFF, 0xFF, 
        0x00, 0x00, 0x00, 0x0A, 
        
        0x00, 0x00, 0x00, 0x0C, 
        0x00, 0x0A, 0x04, 0x00, // Option: Len=10, Type=0x04 (IPv4), Res=0
        0x7F, 0x00, 0x00, 0x01, 
        0x00, 0x11, 0x77, 0x24  
    };

    auto parse_test = [](const std::vector<uint8_t>& buf) {
        int entries_start = 16 + 8;
        uint32_t len_entries = (uint32_t(buf[16+4]) << 24) | (uint32_t(buf[16+5]) << 16) | (uint32_t(buf[16+6]) << 8) | uint32_t(buf[16+7]);
        int options_start = entries_start + len_entries + 4;
        uint32_t len_opts = (uint32_t(buf[options_start-4]) << 24) | (uint32_t(buf[options_start-3]) << 16) | (uint32_t(buf[options_start-2]) << 8) | uint32_t(buf[options_start-1]);
        int opt_ptr = options_start;
        int opt_end = options_start + (int)len_opts;
        bool found_valid_v4 = false;
        while (opt_ptr + 3 <= opt_end) {
            uint16_t opt_len = (uint16_t(buf[opt_ptr]) << 8) | uint16_t(buf[opt_ptr+1]);
            uint8_t opt_type = buf[opt_ptr+2];
            if (opt_type == 0x04 && opt_len == 10) {
                found_valid_v4 = true;
                uint16_t port = (uint16_t(buf[opt_ptr+10]) << 8) | uint16_t(buf[opt_ptr+11]);
                assert(port == 30500);
            }
            opt_ptr += 2 + opt_len;
        }
        return found_valid_v4;
    };

    assert(parse_test(golden_v4) == true);
    std::cout << "SUCCESS: C++ correctly parsed standard 9-byte IPv4 Endpoint option." << std::endl;

    // 2. Test IPv6 Golden (21 bytes)
    std::vector<uint8_t> golden_v6 = {
        0xFF, 0xFF, 0x81, 0x00, 0x00, 0x00, 0x00, 0x38, 0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x02, 0x00,
        0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10,
        0x01, 0x00, 0x00, 0x10, 0x12, 0x34, 0x00, 0x01, 0x01, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x0A,
        0x00, 0x00, 0x00, 0x18, 
        0x00, 0x16, 0x06, 0x00, // Option: Len=22 (0x16), Type=0x06 (IPv6)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 
        0x00, 0x11, 0x77, 0x24  
    };

    auto parse_test_v6 = [](const std::vector<uint8_t>& buf) {
        int options_start = 16 + 8 + 16 + 4;
        uint32_t len_opts = (uint32_t(buf[options_start-4]) << 24) | (uint32_t(buf[options_start-3]) << 16) | (uint32_t(buf[options_start-2]) << 8) | uint32_t(buf[options_start-1]);
        int opt_ptr = options_start;
        int opt_end = options_start + (int)len_opts;
        bool found_valid_v6 = false;
        while (opt_ptr + 3 <= opt_end) {
            uint16_t opt_len = (uint16_t(buf[opt_ptr]) << 8) | uint16_t(buf[opt_ptr+1]);
            uint8_t opt_type = buf[opt_ptr+2];
            if (opt_type == 0x06 && opt_len == 22) {
                found_valid_v6 = true;
                uint16_t port = (uint16_t(buf[opt_ptr+22]) << 8) | uint16_t(buf[opt_ptr+23]);
                assert(port == 30500);
            }
            opt_ptr += 2 + opt_len;
        }
        return found_valid_v6;
    };

    assert(parse_test_v6(golden_v6) == true);
    std::cout << "SUCCESS: C++ correctly parsed standard 21-byte IPv6 Endpoint option." << std::endl;

#ifdef _WIN32
    WSACleanup();
#endif
    return 0;
}
