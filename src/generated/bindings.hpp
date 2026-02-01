#pragma once
#include <vector>
#include <string>
#include <cstdint>
#include <vector>
#include <cstring>
#include <algorithm>


    inline void write_u32_be(std::vector<uint8_t>& buf, uint32_t val) {
        buf.push_back((val >> 24) & 0xFF);
        buf.push_back((val >> 16) & 0xFF);
        buf.push_back((val >> 8) & 0xFF);
        buf.push_back(val & 0xFF);
    }
    
struct RustMathRequest {
    int32_t op;
    int32_t a;
    int32_t b;
    
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        // Serialization logic (Placeholder for MVP)
        return buffer;
    }
};

struct RustMathResponse {
    int32_t result;
    
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        // Serialization logic (Placeholder for MVP)
        return buffer;
    }
};

struct PyStringRequest {
    int32_t op;
    std::string text;
    
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        // Serialization logic (Placeholder for MVP)
        return buffer;
    }
};

struct PyStringResponse {
    std::string result;
    
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        // Serialization logic (Placeholder for MVP)
        return buffer;
    }
};

struct CppSortRequest {
    int32_t method;
    std::vector<int32_t> data;
    
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        // Serialization logic (Placeholder for MVP)
        return buffer;
    }
};

struct CppSortResponse {
    std::vector<int32_t> sorted_data;
    
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        // Serialization logic (Placeholder for MVP)
        return buffer;
    }
};
