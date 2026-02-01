#pragma once
#include <vector>
#include <string>
#include <cstdint>

namespace generated {
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
        buffer.push_back(service_id >> 8); buffer.push_back(service_id);
        buffer.push_back(method_id >> 8); buffer.push_back(method_id);
        buffer.push_back(length >> 24); buffer.push_back(length >> 16); buffer.push_back(length >> 8); buffer.push_back(length);
        buffer.push_back(client_id >> 8); buffer.push_back(client_id);
        buffer.push_back(session_id >> 8); buffer.push_back(session_id);
        buffer.push_back(proto_ver); buffer.push_back(iface_ver); buffer.push_back(msg_type); buffer.push_back(return_code);
        return buffer;
    }
};

// RequestHandler Interface
class RequestHandler {
public:
    virtual uint16_t get_service_id() = 0;
    virtual std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) = 0;
};

// Glue for Clients
void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);

struct SortData {
    std::vector<int32_t> values;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_values = static_cast<uint32_t>(values.size() * 4);
        buffer.push_back(len_values >> 24); buffer.push_back(len_values >> 16); buffer.push_back(len_values >> 8); buffer.push_back(len_values);
        for(int32_t val : values) {
            buffer.push_back(val >> 24); buffer.push_back(val >> 16); buffer.push_back(val >> 8); buffer.push_back(val);
        }
        return buffer;
    }

    // Deserialize
    static SortData deserialize(const uint8_t*& data, size_t& len) {
        SortData obj;
        uint32_t byte_len_values = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        int count_values = byte_len_values / 4;
        for(int i=0; i<count_values; i++) {
             int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
             obj.values.push_back(val);
        }
        return obj;
    }
};
// Service MathService
struct MathServiceAddRequest {
    int32_t a;
    int32_t b;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        buffer.push_back(a >> 24); buffer.push_back(a >> 16); buffer.push_back(a >> 8); buffer.push_back(a);
        buffer.push_back(b >> 24); buffer.push_back(b >> 16); buffer.push_back(b >> 8); buffer.push_back(b);
        return buffer;
    }

    // Deserialize
    static MathServiceAddRequest deserialize(const uint8_t*& data, size_t& len) {
        MathServiceAddRequest obj;
        obj.a = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        obj.b = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        return obj;
    }
};
struct MathServiceAddResponse {
    int32_t result;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        buffer.push_back(result >> 24); buffer.push_back(result >> 16); buffer.push_back(result >> 8); buffer.push_back(result);
        return buffer;
    }

    // Deserialize
    static MathServiceAddResponse deserialize(const uint8_t*& data, size_t& len) {
        MathServiceAddResponse obj;
        obj.result = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        return obj;
    }
};
struct MathServiceSubRequest {
    int32_t a;
    int32_t b;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        buffer.push_back(a >> 24); buffer.push_back(a >> 16); buffer.push_back(a >> 8); buffer.push_back(a);
        buffer.push_back(b >> 24); buffer.push_back(b >> 16); buffer.push_back(b >> 8); buffer.push_back(b);
        return buffer;
    }

    // Deserialize
    static MathServiceSubRequest deserialize(const uint8_t*& data, size_t& len) {
        MathServiceSubRequest obj;
        obj.a = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        obj.b = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        return obj;
    }
};
struct MathServiceSubResponse {
    int32_t result;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        buffer.push_back(result >> 24); buffer.push_back(result >> 16); buffer.push_back(result >> 8); buffer.push_back(result);
        return buffer;
    }

    // Deserialize
    static MathServiceSubResponse deserialize(const uint8_t*& data, size_t& len) {
        MathServiceSubResponse obj;
        obj.result = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        return obj;
    }
};
class MathServiceStub : public RequestHandler {
public:
    static const uint16_t SERVICE_ID = 4097;
    uint16_t get_service_id() override { return SERVICE_ID; }

    virtual MathServiceAddResponse Add(MathServiceAddRequest req) = 0;
    virtual MathServiceSubResponse Sub(MathServiceSubRequest req) = 0;

    std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) override {
        const uint8_t* ptr = payload.data(); size_t len = payload.size();
        switch(header.method_id) {
            case 1: {
                MathServiceAddRequest req = MathServiceAddRequest::deserialize(ptr, len);
                auto res = Add(req);
                return res.serialize();
            }
            case 2: {
                MathServiceSubRequest req = MathServiceSubRequest::deserialize(ptr, len);
                auto res = Sub(req);
                return res.serialize();
            }
        }
        return {};
    }
};
class MathServiceClient {
    void* runtime;
    uint16_t service_id;
    // sockaddr_in not avail here without include, assume runtime handles send
    // But we need to pass target. Let's make pure virtual Send interface on runtime?
    // For simplicity, we assume runtime has SendRequest(sid, payload)
    // We need to pass target IP/Port? 
    // Let's assume Runtime handles lookup or we pass generic pointer/struct.
public:
    static const uint16_t SERVICE_ID = 4097;
    MathServiceClient(void* rt, uint16_t sid) : runtime(rt), service_id(sid) {}
    void Add(int32_t a, int32_t b) {
        MathServiceAddRequest req;
        req.a = a;
        req.b = b;
        std::vector<uint8_t> payload = req.serialize();
        // Cast runtime and call. We need a forward decl or interface for Runtime.
        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'
        // We'll define a 'ISomeIpRuntime' interface at top?
        // Or just template? No, this is generated.
        // Expect user to provide 'ISomeIpRuntime' before including this?
        // Let's use void* and cast, confusing.
        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'
        SendRequestGlue(runtime, service_id, payload);
    }
    void Sub(int32_t a, int32_t b) {
        MathServiceSubRequest req;
        req.a = a;
        req.b = b;
        std::vector<uint8_t> payload = req.serialize();
        // Cast runtime and call. We need a forward decl or interface for Runtime.
        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'
        // We'll define a 'ISomeIpRuntime' interface at top?
        // Or just template? No, this is generated.
        // Expect user to provide 'ISomeIpRuntime' before including this?
        // Let's use void* and cast, confusing.
        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'
        SendRequestGlue(runtime, service_id, payload);
    }
};
// Service StringService
struct StringServiceReverseRequest {
    std::string text;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_text = static_cast<uint32_t>(text.length());
        buffer.push_back(len_text >> 24); buffer.push_back(len_text >> 16); buffer.push_back(len_text >> 8); buffer.push_back(len_text);
        for(char c : text) buffer.push_back(c);
        return buffer;
    }

    // Deserialize
    static StringServiceReverseRequest deserialize(const uint8_t*& data, size_t& len) {
        StringServiceReverseRequest obj;
        uint32_t byte_len_text = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        obj.text.assign(reinterpret_cast<const char*>(data), byte_len_text); data+=byte_len_text; len-=byte_len_text;
        return obj;
    }
};
struct StringServiceReverseResponse {
    std::string result;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_result = static_cast<uint32_t>(result.length());
        buffer.push_back(len_result >> 24); buffer.push_back(len_result >> 16); buffer.push_back(len_result >> 8); buffer.push_back(len_result);
        for(char c : result) buffer.push_back(c);
        return buffer;
    }

    // Deserialize
    static StringServiceReverseResponse deserialize(const uint8_t*& data, size_t& len) {
        StringServiceReverseResponse obj;
        uint32_t byte_len_result = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        obj.result.assign(reinterpret_cast<const char*>(data), byte_len_result); data+=byte_len_result; len-=byte_len_result;
        return obj;
    }
};
struct StringServiceUppercaseRequest {
    std::string text;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_text = static_cast<uint32_t>(text.length());
        buffer.push_back(len_text >> 24); buffer.push_back(len_text >> 16); buffer.push_back(len_text >> 8); buffer.push_back(len_text);
        for(char c : text) buffer.push_back(c);
        return buffer;
    }

    // Deserialize
    static StringServiceUppercaseRequest deserialize(const uint8_t*& data, size_t& len) {
        StringServiceUppercaseRequest obj;
        uint32_t byte_len_text = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        obj.text.assign(reinterpret_cast<const char*>(data), byte_len_text); data+=byte_len_text; len-=byte_len_text;
        return obj;
    }
};
struct StringServiceUppercaseResponse {
    std::string result;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_result = static_cast<uint32_t>(result.length());
        buffer.push_back(len_result >> 24); buffer.push_back(len_result >> 16); buffer.push_back(len_result >> 8); buffer.push_back(len_result);
        for(char c : result) buffer.push_back(c);
        return buffer;
    }

    // Deserialize
    static StringServiceUppercaseResponse deserialize(const uint8_t*& data, size_t& len) {
        StringServiceUppercaseResponse obj;
        uint32_t byte_len_result = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        obj.result.assign(reinterpret_cast<const char*>(data), byte_len_result); data+=byte_len_result; len-=byte_len_result;
        return obj;
    }
};
class StringServiceStub : public RequestHandler {
public:
    static const uint16_t SERVICE_ID = 8193;
    uint16_t get_service_id() override { return SERVICE_ID; }

    virtual StringServiceReverseResponse Reverse(StringServiceReverseRequest req) = 0;
    virtual StringServiceUppercaseResponse Uppercase(StringServiceUppercaseRequest req) = 0;

    std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) override {
        const uint8_t* ptr = payload.data(); size_t len = payload.size();
        switch(header.method_id) {
            case 1: {
                StringServiceReverseRequest req = StringServiceReverseRequest::deserialize(ptr, len);
                auto res = Reverse(req);
                return res.serialize();
            }
            case 2: {
                StringServiceUppercaseRequest req = StringServiceUppercaseRequest::deserialize(ptr, len);
                auto res = Uppercase(req);
                return res.serialize();
            }
        }
        return {};
    }
};
class StringServiceClient {
    void* runtime;
    uint16_t service_id;
    // sockaddr_in not avail here without include, assume runtime handles send
    // But we need to pass target. Let's make pure virtual Send interface on runtime?
    // For simplicity, we assume runtime has SendRequest(sid, payload)
    // We need to pass target IP/Port? 
    // Let's assume Runtime handles lookup or we pass generic pointer/struct.
public:
    static const uint16_t SERVICE_ID = 8193;
    StringServiceClient(void* rt, uint16_t sid) : runtime(rt), service_id(sid) {}
    void Reverse(std::string text) {
        StringServiceReverseRequest req;
        req.text = text;
        std::vector<uint8_t> payload = req.serialize();
        // Cast runtime and call. We need a forward decl or interface for Runtime.
        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'
        // We'll define a 'ISomeIpRuntime' interface at top?
        // Or just template? No, this is generated.
        // Expect user to provide 'ISomeIpRuntime' before including this?
        // Let's use void* and cast, confusing.
        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'
        SendRequestGlue(runtime, service_id, payload);
    }
    void Uppercase(std::string text) {
        StringServiceUppercaseRequest req;
        req.text = text;
        std::vector<uint8_t> payload = req.serialize();
        // Cast runtime and call. We need a forward decl or interface for Runtime.
        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'
        // We'll define a 'ISomeIpRuntime' interface at top?
        // Or just template? No, this is generated.
        // Expect user to provide 'ISomeIpRuntime' before including this?
        // Let's use void* and cast, confusing.
        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'
        SendRequestGlue(runtime, service_id, payload);
    }
};
// Service SortService
struct SortServiceSortAscRequest {
    std::vector<int32_t> data;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_data = static_cast<uint32_t>(data.size() * 4);
        buffer.push_back(len_data >> 24); buffer.push_back(len_data >> 16); buffer.push_back(len_data >> 8); buffer.push_back(len_data);
        for(int32_t val : data) {
            buffer.push_back(val >> 24); buffer.push_back(val >> 16); buffer.push_back(val >> 8); buffer.push_back(val);
        }
        return buffer;
    }

    // Deserialize
    static SortServiceSortAscRequest deserialize(const uint8_t*& data, size_t& len) {
        SortServiceSortAscRequest obj;
        uint32_t byte_len_data = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        int count_data = byte_len_data / 4;
        for(int i=0; i<count_data; i++) {
             int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
             obj.data.push_back(val);
        }
        return obj;
    }
};
struct SortServiceSortAscResponse {
    std::vector<int32_t> result;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_result = static_cast<uint32_t>(result.size() * 4);
        buffer.push_back(len_result >> 24); buffer.push_back(len_result >> 16); buffer.push_back(len_result >> 8); buffer.push_back(len_result);
        for(int32_t val : result) {
            buffer.push_back(val >> 24); buffer.push_back(val >> 16); buffer.push_back(val >> 8); buffer.push_back(val);
        }
        return buffer;
    }

    // Deserialize
    static SortServiceSortAscResponse deserialize(const uint8_t*& data, size_t& len) {
        SortServiceSortAscResponse obj;
        uint32_t byte_len_result = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        int count_result = byte_len_result / 4;
        for(int i=0; i<count_result; i++) {
             int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
             obj.result.push_back(val);
        }
        return obj;
    }
};
struct SortServiceSortDescRequest {
    std::vector<int32_t> data;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_data = static_cast<uint32_t>(data.size() * 4);
        buffer.push_back(len_data >> 24); buffer.push_back(len_data >> 16); buffer.push_back(len_data >> 8); buffer.push_back(len_data);
        for(int32_t val : data) {
            buffer.push_back(val >> 24); buffer.push_back(val >> 16); buffer.push_back(val >> 8); buffer.push_back(val);
        }
        return buffer;
    }

    // Deserialize
    static SortServiceSortDescRequest deserialize(const uint8_t*& data, size_t& len) {
        SortServiceSortDescRequest obj;
        uint32_t byte_len_data = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        int count_data = byte_len_data / 4;
        for(int i=0; i<count_data; i++) {
             int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
             obj.data.push_back(val);
        }
        return obj;
    }
};
struct SortServiceSortDescResponse {
    std::vector<int32_t> result;

    // Serialize
    std::vector<uint8_t> serialize() const {
        std::vector<uint8_t> buffer;
        uint32_t len_result = static_cast<uint32_t>(result.size() * 4);
        buffer.push_back(len_result >> 24); buffer.push_back(len_result >> 16); buffer.push_back(len_result >> 8); buffer.push_back(len_result);
        for(int32_t val : result) {
            buffer.push_back(val >> 24); buffer.push_back(val >> 16); buffer.push_back(val >> 8); buffer.push_back(val);
        }
        return buffer;
    }

    // Deserialize
    static SortServiceSortDescResponse deserialize(const uint8_t*& data, size_t& len) {
        SortServiceSortDescResponse obj;
        uint32_t byte_len_result = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
        int count_result = byte_len_result / 4;
        for(int i=0; i<count_result; i++) {
             int32_t val = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]; data+=4; len-=4;
             obj.result.push_back(val);
        }
        return obj;
    }
};
class SortServiceStub : public RequestHandler {
public:
    static const uint16_t SERVICE_ID = 12289;
    uint16_t get_service_id() override { return SERVICE_ID; }

    virtual SortServiceSortAscResponse SortAsc(SortServiceSortAscRequest req) = 0;
    virtual SortServiceSortDescResponse SortDesc(SortServiceSortDescRequest req) = 0;

    std::vector<uint8_t> handle(const SomeIpHeader& header, const std::vector<uint8_t>& payload) override {
        const uint8_t* ptr = payload.data(); size_t len = payload.size();
        switch(header.method_id) {
            case 1: {
                SortServiceSortAscRequest req = SortServiceSortAscRequest::deserialize(ptr, len);
                auto res = SortAsc(req);
                return res.serialize();
            }
            case 2: {
                SortServiceSortDescRequest req = SortServiceSortDescRequest::deserialize(ptr, len);
                auto res = SortDesc(req);
                return res.serialize();
            }
        }
        return {};
    }
};
class SortServiceClient {
    void* runtime;
    uint16_t service_id;
    // sockaddr_in not avail here without include, assume runtime handles send
    // But we need to pass target. Let's make pure virtual Send interface on runtime?
    // For simplicity, we assume runtime has SendRequest(sid, payload)
    // We need to pass target IP/Port? 
    // Let's assume Runtime handles lookup or we pass generic pointer/struct.
public:
    static const uint16_t SERVICE_ID = 12289;
    SortServiceClient(void* rt, uint16_t sid) : runtime(rt), service_id(sid) {}
    void SortAsc(std::vector<int32_t> data) {
        SortServiceSortAscRequest req;
        req.data = data;
        std::vector<uint8_t> payload = req.serialize();
        // Cast runtime and call. We need a forward decl or interface for Runtime.
        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'
        // We'll define a 'ISomeIpRuntime' interface at top?
        // Or just template? No, this is generated.
        // Expect user to provide 'ISomeIpRuntime' before including this?
        // Let's use void* and cast, confusing.
        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'
        SendRequestGlue(runtime, service_id, payload);
    }
    void SortDesc(std::vector<int32_t> data) {
        SortServiceSortDescRequest req;
        req.data = data;
        std::vector<uint8_t> payload = req.serialize();
        // Cast runtime and call. We need a forward decl or interface for Runtime.
        // Hack: Runtime must have 'SendRequest(uint16_t, vector)'
        // We'll define a 'ISomeIpRuntime' interface at top?
        // Or just template? No, this is generated.
        // Expect user to provide 'ISomeIpRuntime' before including this?
        // Let's use void* and cast, confusing.
        // Better: Expect 'extern void SendRequestGlue(void* rt, uint16_t sid, const std::vector<uint8_t>& payload);'
        SendRequestGlue(runtime, service_id, payload);
    }
};
} // namespace generated