#include "fusion_hawking/tp.hpp"
#include <sstream>
#include <iostream>
#include <algorithm>
#include <cstring>

namespace fusion_hawking {

std::vector<uint8_t> TpHeader::serialize() const {
    std::vector<uint8_t> buf(4);
    uint32_t val = (offset << 4) | (more_segments ? 1 : 0);
    buf[0] = (val >> 24) & 0xFF;
    buf[1] = (val >> 16) & 0xFF;
    buf[2] = (val >> 8) & 0xFF;
    buf[3] = val & 0xFF;
    return buf;
}

TpHeader TpHeader::deserialize(const uint8_t* buffer, size_t len) {
    if (len < 4) return {0, false};
    uint32_t val = (buffer[0] << 24) | (buffer[1] << 16) | (buffer[2] << 8) | buffer[3];
    TpHeader h;
    h.offset = val >> 4;
    h.more_segments = (val & 0x01) != 0;
    return h;
}

bool TpReassembler::process_segment(uint16_t service_id, uint16_t method_id, uint16_t client_id, uint16_t session_id, const TpHeader& header, const std::vector<uint8_t>& payload, std::vector<uint8_t>& out_payload) {
    std::stringstream key_ss;
    key_ss << service_id << ":" << method_id << ":" << client_id << ":" << session_id;
    std::string key = key_ss.str();

    auto& session = buffers[key];

    // Check alignment
    if (header.more_segments && (payload.size() % 16 != 0)) {
        std::cerr << "[TP] Dropping invalid segment: More=1 but len=" << payload.size() << " not aligned." << std::endl;
        buffers.erase(key);
        return false;
    }

    session.segments[header.offset] = payload;

    if (!header.more_segments) {
        session.last_offset_received = true;
        session.expected_total_length = (header.offset * 16) + payload.size();
    }

    if (session.last_offset_received) {
        // Check continuity
        uint32_t current_offset = 0; // expected offset 0
        uint32_t byte_offset = 0;
        
        bool contiguous = true;
        
        // Map is sorted by key (offset)
        if (session.segments.empty() || session.segments.begin()->first != 0) return false;

        for (auto const& [off, chunk] : session.segments) {
             // 'off' is in 16-byte units.
             // If byte_offset (bytes received so far) != off * 16, then gap.
             if (off * 16 != byte_offset) {
                 contiguous = false;
                 break;
             }
             byte_offset += chunk.size();
        }

        if (contiguous && byte_offset == session.expected_total_length) {
            // Reassemble
            out_payload.clear();
            out_payload.reserve(session.expected_total_length);
            for (auto const& [off, chunk] : session.segments) {
                out_payload.insert(out_payload.end(), chunk.begin(), chunk.end());
            }
            buffers.erase(key);
            return true;
        }
    }
    return false;
}

std::vector<std::pair<TpHeader, std::vector<uint8_t>>> segment_payload(const std::vector<uint8_t>& payload, uint32_t max_segment_size) {
    std::vector<std::pair<TpHeader, std::vector<uint8_t>>> segments;
    size_t total_len = payload.size();
    size_t current_pos = 0; // bytes

    while (current_pos < total_len) {
        size_t remaining = total_len - current_pos;
        size_t chunk_size = std::min((size_t)max_segment_size, remaining);

        // Align if not last
        bool more = false;
        if (remaining > max_segment_size) {
            chunk_size = (chunk_size / 16) * 16;
            more = true;
        } else {
             more = false;
        }

        TpHeader h;
        h.offset = (uint32_t)(current_pos / 16);
        h.more_segments = more;

        std::vector<uint8_t> chunk(payload.begin() + current_pos, payload.begin() + current_pos + chunk_size);
        segments.push_back({h, chunk});
        
        current_pos += chunk_size;
    }
    return segments;
}

}
