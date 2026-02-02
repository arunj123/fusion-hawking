#pragma once
#include <vector>
#include <cstdint>

namespace fusion_hawking {

struct SomeIpHeader {
    uint16_t service_id; uint16_t method_id; uint32_t length;
    uint16_t client_id; uint16_t session_id;
    uint8_t proto_ver; uint8_t iface_ver; uint8_t msg_type; uint8_t return_code;

    static SomeIpHeader deserialize(const std::vector<uint8_t>& data) {
        SomeIpHeader h = {0};
        if (data.size() < 16) return h;
        h.service_id = (data[0] << 8) | data[1];
        h.method_id = (data[2] << 8) | data[3];
        h.length = (data[4] << 24) | (data[5] << 16) | (data[6] << 8) | data[7];
        h.client_id = (data[8] << 8) | data[9];
        h.session_id = (data[10] << 8) | data[11];
        h.proto_ver = data[12]; h.iface_ver = data[13]; h.msg_type = data[14]; h.return_code = data[15];
        return h;
    }

    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        buffer.push_back(static_cast<uint8_t>(service_id >> 8)); buffer.push_back(static_cast<uint8_t>(service_id & 0xFF));
        buffer.push_back(static_cast<uint8_t>(method_id >> 8)); buffer.push_back(static_cast<uint8_t>(method_id & 0xFF));
        buffer.push_back(static_cast<uint8_t>(length >> 24)); buffer.push_back(static_cast<uint8_t>(length >> 16));
        buffer.push_back(static_cast<uint8_t>(length >> 8)); buffer.push_back(static_cast<uint8_t>(length & 0xFF));
        buffer.push_back(static_cast<uint8_t>(client_id >> 8)); buffer.push_back(static_cast<uint8_t>(client_id & 0xFF));
        buffer.push_back(static_cast<uint8_t>(session_id >> 8)); buffer.push_back(static_cast<uint8_t>(session_id & 0xFF));
        buffer.push_back(proto_ver); buffer.push_back(iface_ver); buffer.push_back(msg_type); buffer.push_back(return_code);
        return buffer;
    }
};

class RequestHandler {
public:
    virtual ~RequestHandler() = default;
    virtual uint16_t get_service_id() = 0;
    virtual std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) = 0;
};

// Glue for Clients
void SendRequestGlue(void* rt, uint16_t sid, uint16_t mid, const std::vector<uint8_t>& payload);

} // namespace fusion_hawking
