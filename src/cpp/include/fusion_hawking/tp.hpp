#pragma once
#include <vector>
#include <cstdint>
#include <map>
#include <string>

namespace fusion_hawking {

struct TpHeader {
    uint32_t offset;
    bool more_segments;
    
    std::vector<uint8_t> serialize() const;
    static TpHeader deserialize(const uint8_t* buffer, size_t len);
};

class TpReassembler {
    struct SessionBuffer {
        std::map<uint32_t, std::vector<uint8_t>> segments; // offset -> data
        bool last_offset_received = false;
        uint32_t expected_total_length = 0;
    };
    
    // Key: "service:method:client:session"
    std::map<std::string, SessionBuffer> buffers;
    
public:
    // Returns empty vector if not complete, or full payload if complete.
    // Note: Empty vector could strictly mean "empty payload", but here assume it means "incomplete".
    // Alternatively return std::optional or bool+vector. 
    // Let's return bool (complete) and output param.
    bool process_segment(uint16_t service_id, uint16_t method_id, uint16_t client_id, uint16_t session_id, const TpHeader& header, const std::vector<uint8_t>& payload, std::vector<uint8_t>& out_payload);
};

std::vector<std::pair<TpHeader, std::vector<uint8_t>>> segment_payload(const std::vector<uint8_t>& payload, uint32_t max_segment_size = 1392);

}
