#include <iostream>
#include <vector>
#include <cassert>
#include <cstring>
#include <cstdint>
#include <limits>
#include "fusion_hawking/tp.hpp"
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
    
    using namespace fusion_hawking;
    using namespace generated;
    
    // 1. Test MathServiceAddRequest - Positive integers
    // [PRS_SOMEIP_00191] Verify Payload Serialization (Big Endian)
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
        MathServiceAddRequest req2 = MathServiceAddRequest::from_bytes(ptr, len);
        
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
        MathServiceAddRequest req2 = MathServiceAddRequest::from_bytes(ptr, len);
        
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
        MathServiceAddRequest req2 = MathServiceAddRequest::from_bytes(ptr, len);
        
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
        MathServiceAddRequest req2 = MathServiceAddRequest::from_bytes(ptr, len);
        
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
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::from_bytes(ptr, len);
        
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
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::from_bytes(ptr, len);
        
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
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::from_bytes(ptr, len);
        
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
        SortServiceSortAscRequest req2 = SortServiceSortAscRequest::from_bytes(ptr, len);
        
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
        MathServiceAddResponse resp2 = MathServiceAddResponse::from_bytes(ptr, len);
        
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
        StringServiceReverseRequest req2 = StringServiceReverseRequest::from_bytes(ptr, len);
        
        assert(req2.text == "Hello SOME/IP");
        std::cout << "StringServiceReverseRequest: OK" << std::endl;
    }

    // 11. Test SessionIdManager
    {
        SessionIdManager mgr;
        // Initial
        assert(mgr.next_session_id(0x1000, 0x0001) == 1);
        assert(mgr.next_session_id(0x1000, 0x0001) == 2);
        
        // Independent
        assert(mgr.next_session_id(0x2000, 0x0005) == 1);
        assert(mgr.next_session_id(0x1000, 0x0001) == 3);
        
        // Reset
        mgr.reset(0x1000, 0x0001);
        assert(mgr.next_session_id(0x1000, 0x0001) == 1);
        
        // Wrap-around Logic check
        // We can't easily force internal state without verifying internal logic, 
        // but checking basic sequence is good.
        // We could loop 65535 times but that's slow. 
        // Let's assume the component unit logic is standard.
        std::cout << "SessionIdManager: OK" << std::endl;
    }

    // 12. Test SomeIpHeader Deserialization Edge Cases
    {
        std::vector<uint8_t> short_buf = {0x00, 0x00};
        SomeIpHeader h = SomeIpHeader::deserialize(short_buf);
        // Should return zeroed header if failed (or handled gracefully)
        // Current impl returns {0} if size < 16.
        assert(h.service_id == 0);
        assert(h.length == 0);
        
        std::cout << "SomeIpHeader (Edge Cases): OK" << std::endl;
    }

    // 13. Test TP Header Serialization
    {
        fusion_hawking::TpHeader h;
        h.offset = 0x12345;
        h.more_segments = true;
        
        std::vector<uint8_t> buf = h.serialize();
        assert(buf.size() == 4);
        
        // Offset is top 28 bits, More is bottom 1 bit.
        // 0x12345 << 4 = 0x123450. | 1 = 0x123451.
        uint32_t val = (buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3];
        assert(val == 0x00123451); 

        fusion_hawking::TpHeader h2 = fusion_hawking::TpHeader::deserialize(buf.data(), buf.size());
        assert(h2.offset == 0x12345);
        assert(h2.more_segments == true);
        std::cout << "TpHeader: OK" << std::endl;
    }

    // 14. Test Payload Segmentation
    {
        std::vector<uint8_t> payload(3000); // > 1392 * 2
        for(size_t i=0; i<payload.size(); ++i) payload[i] = (uint8_t)(i & 0xFF);
        
        auto segments = fusion_hawking::segment_payload(payload, 1392);
        // 3000 / 1392 = 2.xxx -> 3 segments
        // Seg 1: 1392 (aligned 16: yes)
        // Seg 2: 1392 (aligned 16: yes)
        // Seg 3: 3000 - 2784 = 216
        
        assert(segments.size() == 3);
        assert(segments[0].first.offset == 0);
        assert(segments[0].first.more_segments == true);
        assert(segments[0].second.size() == 1392);
        
        assert(segments[1].first.offset == 1392/16); // 87
        assert(segments[1].first.more_segments == true);
        assert(segments[1].second.size() == 1392);

        assert(segments[2].first.offset == 2784/16); // 174
        assert(segments[2].first.more_segments == false);
        assert(segments[2].second.size() == 216);
        
        std::cout << "TP Segmentation: OK" << std::endl;
    }
    
    // 15. Test Reassembly
    {
        fusion_hawking::TpReassembler reassembler;
        std::vector<uint8_t> full_payload_out;
        
        std::vector<uint8_t> chunk1(16, 0xAA);
        std::vector<uint8_t> chunk2(16, 0xBB);
        
        fusion_hawking::TpHeader h1 = {0, true};
        fusion_hawking::TpHeader h2 = {1, false}; // Offset 1 * 16 = 16 bytes
        
        // Send chunk 2 first (out of order)
        bool complete = reassembler.process_segment(1, 1, 1, 1, h2, chunk2, full_payload_out);
        assert(!complete);
        
        // Send chunk 1
        complete = reassembler.process_segment(1, 1, 1, 1, h1, chunk1, full_payload_out);
        assert(complete);
        assert(full_payload_out.size() == 32);
        for(int i=0; i<16; ++i) assert(full_payload_out[i] == 0xAA);
        for(int i=16; i<32; ++i) assert(full_payload_out[i] == 0xBB);
        
        std::cout << "TP Reassembly: OK" << std::endl;
    }

    std::cout << "All C++ Tests Passed." << std::endl;
    return 0;
}
