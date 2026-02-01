#pragma once
#include <vector>
#include <string>
#include <cstdint>

namespace generated {
struct SortData {
    std::vector<int32_t> values;
};
// Service MathService
struct MathServiceAddRequest {
    int32_t a;
    int32_t b;
};
struct MathServiceAddResponse {
    int32_t result;
};
struct MathServiceSubRequest {
    int32_t a;
    int32_t b;
};
struct MathServiceSubResponse {
    int32_t result;
};
// Service StringService
struct StringServiceReverseRequest {
    std::string text;
};
struct StringServiceReverseResponse {
    std::string result;
};
struct StringServiceUppercaseRequest {
    std::string text;
};
struct StringServiceUppercaseResponse {
    std::string result;
};
// Service SortService
struct SortServiceSortAscRequest {
    std::vector<int32_t> data;
};
struct SortServiceSortAscResponse {
    std::vector<int32_t> result;
};
struct SortServiceSortDescRequest {
    std::vector<int32_t> data;
};
struct SortServiceSortDescResponse {
    std::vector<int32_t> result;
};
} // namespace generated