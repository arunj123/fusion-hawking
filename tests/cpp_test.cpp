#include <iostream>
#include <vector>
#include <cassert>
#include <cstring>
#include <cstdint>
#include <limits>
#include "bindings.h"  // Located in build/generated/cpp/ via CMake include path

// Helper to verify big-endian encoding
uint32_t read_be32(const uint8_t* data) {
    return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3];
}

int32_t read_be32_signed(const uint8_t* data) {
    uint32_t u = read_be32(data);
    return static_cast<int32_t>(u);
}

int main() {
    std::cout << "Running C++ Serialization Tests..." << std::endl;
    
    using namespace generated;
    
    // 1. Test MathServiceAddRequest - Positive integers
    {
        MathServiceAddRequest req;
        req.a = 100;
        req.b = 200;
        
        std::vector<uint8_t> buffer = req.serialize();
        assert(buffer.size() == 8);
        
        // Verify big-endian encoding
        assert(read_be32_signed(buffer.data()) == 100);
        assert(read_be32_signed(buffer.data() + 4) == 200);
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        MathServiceAddRequest req2 = MathServiceAddRequest::deserialize(ptr, len);
        
        assert(req2.a == 100);
        assert(req2.b == 200);
        std::cout << "MathServiceAddRequest (positive): OK" << std::endl;
    }
    
    // 2. Test MathServiceAddRequest - Negative integers
    {
        MathServiceAddRequest req;
        req.a = -50;
        req.b = -100;
        
        std::vector<uint8_t> buffer = req.serialize();
        assert(buffer.size() == 8);
        
        // Verify two's complement
        assert(read_be32_signed(buffer.data()) == -50);
        assert(read_be32_signed(buffer.data() + 4) == -100);
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        MathServiceAddRequest req2 = MathServiceAddRequest::deserialize(ptr, len);
        
        assert(req2.a == -50);
        assert(req2.b == -100);
        std::cout << "MathServiceAddRequest (negative): OK" << std::endl;
    }
    
    // 3. Test boundary values
    {
        MathServiceAddRequest req;
        req.a = std::numeric_limits<int32_t>::max();
        req.b = std::numeric_limits<int32_t>::min();
        
        std::vector<uint8_t> buffer = req.serialize();
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        MathServiceAddRequest req2 = MathServiceAddRequest::deserialize(ptr, len);
        
        assert(req2.a == std::numeric_limits<int32_t>::max());
        assert(req2.b == std::numeric_limits<int32_t>::min());
        std::cout << "MathServiceAddRequest (boundary): OK" << std::endl;
    }
    
    // 4. Test zero values
    {
        MathServiceAddRequest req;
        req.a = 0;
        req.b = 0;
        
        std::vector<uint8_t> buffer = req.serialize();
        
        // All zeros
        for (size_t i = 0; i < buffer.size(); i++) {
            assert(buffer[i] == 0);
        }
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        MathServiceAddRequest req2 = MathServiceAddRequest::deserialize(ptr, len);
        
        assert(req2.a == 0);
        assert(req2.b == 0);
        std::cout << "MathServiceAddRequest (zero): OK" << std::endl;
    }
    
    // 5. Test List Serialization - Normal case
    {
        SortServiceSortAscRequest req;
        req.data = {10, 20, 30, 40, 50};
        
        std::vector<uint8_t> buffer = req.serialize();
        // Size: 4 (length) + 5 * 4 (elements) = 24 bytes
        assert(buffer.size() == 24);
        
        // Length field (5 elements * 4 bytes = 20)
        assert(read_be32(buffer.data()) == 20);
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::deserialize(ptr, len);
        
        assert(req2.data.size() == 5);
        assert(req2.data[0] == 10);
        assert(req2.data[4] == 50);
        std::cout << "SortServiceSortAscRequest (normal): OK" << std::endl;
    }
    
    // 6. Test List with negative numbers
    {
        SortServiceSortAscRequest req;
        req.data = {-100, -50, 0, 50, 100};
        
        std::vector<uint8_t> buffer = req.serialize();
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::deserialize(ptr, len);
        
        assert(req2.data[0] == -100);
        assert(req2.data[1] == -50);
        assert(req2.data[2] == 0);
        std::cout << "SortServiceSortAscRequest (negative): OK" << std::endl;
    }
    
    // 7. Test empty list
    {
        SortServiceSortAscRequest req;
        req.data = {};
        
        std::vector<uint8_t> buffer = req.serialize();
        // Size: 4 (length only)
        assert(buffer.size() == 4);
        assert(read_be32(buffer.data()) == 0);
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::deserialize(ptr, len);
        
        assert(req2.data.empty());
        std::cout << "SortServiceSortAscRequest (empty): OK" << std::endl;
    }
    
    // 8. Test single element list
    {
        SortServiceSortAscRequest req;
        req.data = {42};
        
        std::vector<uint8_t> buffer = req.serialize();
        assert(buffer.size() == 8); // 4 + 4
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::deserialize(ptr, len);
        
        assert(req2.data.size() == 1);
        assert(req2.data[0] == 42);
        std::cout << "SortServiceSortAscRequest (single): OK" << std::endl;
    }
    
    // 9. Test Response serialization
    {
        MathServiceAddResponse resp;
        resp.result = 12345;
        
        std::vector<uint8_t> buffer = resp.serialize();
        assert(buffer.size() == 4);
        assert(read_be32_signed(buffer.data()) == 12345);
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        MathServiceAddResponse resp2 = MathServiceAddResponse::deserialize(ptr, len);
        
        assert(resp2.result == 12345);
        std::cout << "MathServiceAddResponse: OK" << std::endl;
    }

    // 10. Test String Serialization
    {
        StringServiceReverseRequest req;
        req.text = "Hello SOME/IP";
        
        std::vector<uint8_t> buffer = req.serialize();
        // 4 (length) + 13 (chars) = 17 bytes
        assert(buffer.size() == 17);
        assert(read_be32(buffer.data()) == 13);
        
        const uint8_t* ptr = buffer.data();
        size_t len = buffer.size();
        StringServiceReverseRequest req2 = StringServiceReverseRequest::deserialize(ptr, len);
        
        assert(req2.text == "Hello SOME/IP");
        std::cout << "StringServiceReverseRequest: OK" << std::endl;
    }

    std::cout << "All C++ Tests Passed." << std::endl;
    return 0;
}
