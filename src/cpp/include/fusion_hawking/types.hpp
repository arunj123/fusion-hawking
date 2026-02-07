#pragma once
#include <vector>
#include <cstdint>
#include <map>
#include <utility>

namespace fusion_hawking {

/// SOME/IP Message Types as defined in AUTOSAR spec [PRS_SOMEIP_00034]
enum class MessageType : uint8_t {
    Request = 0x00,
    RequestNoReturn = 0x01,
    Notification = 0x02,
    RequestWithTp = 0x20,
    RequestNoReturnWithTp = 0x21,
    NotificationWithTp = 0x22,
    Response = 0x80,
    Error = 0x81,
    ResponseWithTp = 0xA0,
    ErrorWithTp = 0xA1
};

/// SOME/IP Return Codes as defined in AUTOSAR spec [PRS_SOMEIP_00043]
enum class ReturnCode : uint8_t {
    Ok = 0x00,
    NotOk = 0x01,
    UnknownService = 0x02,
    UnknownMethod = 0x03,
    NotReady = 0x04,
    NotReachable = 0x05,
    Timeout = 0x06,
    WrongProtocolVersion = 0x07,
    WrongInterfaceVersion = 0x08,
    MalformedMessage = 0x09,
    WrongMessageType = 0x0A,
    E2eRepeated = 0x0B,
    E2eWrongSequence = 0x0C,
    E2eNotAvailable = 0x0D,
    E2eNoNewData = 0x0E
};

/// Manages session IDs per (service_id, method_id) pair
class SessionIdManager {
public:
    uint16_t next_session_id(uint16_t service_id, uint16_t method_id) {
        auto key = std::make_pair(service_id, method_id);
        auto it = counters_.find(key);
        if (it == counters_.end()) {
            counters_[key] = 2;
            return 1;
        }
        uint16_t current = it->second;
        counters_[key] = (current == 0xFFFF) ? 1 : current + 1;
        return current;
    }
    
    void reset(uint16_t service_id, uint16_t method_id) {
        counters_[std::make_pair(service_id, method_id)] = 1;
    }
    
    void reset_all() { counters_.clear(); }
    
private:
    std::map<std::pair<uint16_t, uint16_t>, uint16_t> counters_;
};

/// [PRS_SOMEIP_00030] Header Format
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
    virtual uint32_t get_major_version() = 0;
    virtual uint32_t get_minor_version() = 0;
    virtual std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) = 0;
};

// Glue for Clients
std::vector<uint8_t> SendRequestGlue(void* rt, uint16_t sid, uint16_t mid, const std::vector<uint8_t>& payload);

} // namespace fusion_hawking
