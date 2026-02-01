#include <iostream>
#include <vector>
#include <cassert>
#include <cstring>
#include "../src/generated/bindings.h"

// Mock implementation of main for independent testing
int main() {
    std::cout << "Running C++ Serialization Tests..." << std::endl;
    
    using namespace generated;
    
    // 1. Test MathServiceAddRequest
    {
        MathServiceAddRequest req;
        req.a = 100;
        req.b = -50;
        
        std::vector<uint8_t> buffer = req.serialize();
        // Size: 4 (a) + 4 (b) = 8
        assert(buffer.size() == 8);
        
        // Verify Content (Big Endian)
        // 100 = 0x00000064
        assert(buffer[0] == 0x00 && buffer[3] == 0x64);
        // -50 = 0xFFFFFFCE (Two's complement)
        assert(buffer[4] == 0xFF && buffer[7] == 0xCE);
        
        std::cout << "MathServiceAddRequest Serialization: OK" << std::endl;
        
        // Deserialize
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        MathServiceAddRequest req2 = MathServiceAddRequest::deserialize(ptr, len);
        
        assert(req2.a == 100);
        assert(req2.b == -50);
        std::cout << "MathServiceAddRequest Deserialization: OK" << std::endl;
    }
    
    // 2. Test List Serialization (SortService)
    {
        SortServiceSortAscRequest req;
        req.data = {10, 20, 30};
        
        std::vector<uint8_t> buffer = req.serialize();
        // Size: 4 (len) + 3 * 4 (items) = 16 bytes
        assert(buffer.size() == 16);
        
        // Check Length field (3 * 4 = 12 bytes ??? Wait, how did I generate lists?)
        // Let's check generator... "uint32_t len_name = name.size() * 4;"
        // So it writes BYTES length, not ELEMENT count.
        // 3 elements * 4 bytes = 12.
        assert(buffer[3] == 12);
        
        std::cout << "SortServiceSortAscRequest Serialization: OK" << std::endl;
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::deserialize(ptr, len);
        
        assert(req2.data.size() == 3);
        assert(req2.data[0] == 10);
        assert(req2.data[2] == 30);
        std::cout << "SortServiceSortAscRequest Deserialization: OK" << std::endl;
    }

    std::cout << "All C++ Tests Passed." << std::endl;
    return 0;
}
