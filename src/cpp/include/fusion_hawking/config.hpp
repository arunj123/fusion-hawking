#pragma once
#include <string>
#include <vector>
#include <map>
#include <fstream>
#include <sstream>
#include <iostream>
#include <algorithm>

namespace fusion_hawking {

struct ServiceConfig {
    uint16_t service_id = 0;
    uint16_t instance_id = 1;
    uint8_t major_version = 1;
    uint32_t minor_version = 0;
    std::string endpoint;
    std::string multicast;
};

struct EndpointConfig {
    std::string interface;
    std::string ip;
    int version = 4;
    int port = 0;
    std::string protocol = "udp";
};

struct ClientConfig {
    uint16_t service_id = 0;
    uint16_t instance_id = 1;
    uint8_t major_version = 1;
    uint32_t minor_version = 0;
    std::string endpoint;
};

struct SdConfig {
    uint32_t cycle_offer_ms = 500;
    uint32_t request_response_delay_ms = 50;
    uint32_t request_timeout_ms = 2000;
};

struct InstanceConfig {
    std::string ip;
    std::string ip_v6;
    int ip_version = 4;
    std::map<std::string, ServiceConfig> providing;
    std::map<std::string, ClientConfig> required;
    std::map<std::string, EndpointConfig> endpoints;
    SdConfig sd;
    
    // Config helpers
    std::string sd_multicast_endpoint;
    std::string sd_multicast_endpoint_v6;
};

class ConfigLoader {
public:
    static InstanceConfig Load(const std::string& path, const std::string& instance_name) {
        InstanceConfig config;
        std::ifstream f(path);
        if (!f.is_open()) return config;
        
        std::stringstream buffer;
        buffer << f.rdbuf();
        std::string json = buffer.str();

        // 1. Parse Endpoints (Global)
        size_t endp_pos = json.find("\"endpoints\"");
        if (endp_pos != std::string::npos) {
             size_t e_start = json.find("{", endp_pos);
             size_t e_end = e_start + 1; int e_depth = 1;
             while (e_depth > 0 && e_end < json.length()) {
                 if (json[e_end] == '{') e_depth++;
                 else if (json[e_end] == '}') e_depth--;
                 e_end++;
             }
             ParseEndpoints(json.substr(e_start, e_end - e_start), config.endpoints);
        }

        size_t inst_pos = json.find("\"" + instance_name + "\"");
        if (inst_pos == std::string::npos) return config;
        
        size_t start = json.find("{", inst_pos);
        size_t end = start;
        int depth = 0;
        do {
            if (json[end] == '{') depth++;
            else if (json[end] == '}') depth--;
            end++;
        } while (depth > 0 && end < json.length());
        
        std::string block = json.substr(start, end - start);
        
        size_t prov_pos = block.find("\"providing\"");
        if (prov_pos != std::string::npos) {
            size_t p_start = block.find("{", prov_pos);
            int p_depth = 1; size_t p_end = p_start + 1;
            while (p_depth > 0 && p_end < block.length()) {
                if (block[p_end] == '{') p_depth++;
                else if (block[p_end] == '}') p_depth--;
                p_end++;
            }
            ParseProviding(block.substr(p_start, p_end - p_start), config.providing);
        }

        size_t req_pos = block.find("\"required\"");
        if (req_pos != std::string::npos) {
            size_t r_start = block.find("{", req_pos);
            int r_depth = 1; size_t r_end = r_start + 1;
            while (r_depth > 0 && r_end < block.length()) {
                if (block[r_end] == '{') r_depth++;
                else if (block[r_end] == '}') r_depth--;
                r_end++;
            }
            ParseRequired(block.substr(r_start, r_end - r_start), config.required);
        }

        size_t sd_pos = block.find("\"sd\"");
        if (sd_pos != std::string::npos) {
            size_t sd_start = block.find("{", sd_pos);
            int sd_depth = 1; size_t sd_end = sd_start + 1;
            while (sd_depth > 0 && sd_end < block.length()) {
                if (block[sd_end] == '{') sd_depth++;
                else if (block[sd_end] == '}') sd_depth--;
                sd_end++;
            }
            std::string sd_block = block.substr(sd_start, sd_end - sd_start);
            config.sd_multicast_endpoint = ExtractString(sd_block, "multicast_endpoint");
            config.sd_multicast_endpoint_v6 = ExtractString(sd_block, "multicast_endpoint_v6");
            int cycle = ExtractInt(sd_block, "cycle_offer_ms"); if (cycle > 0) config.sd.cycle_offer_ms = cycle;
            int delay = ExtractInt(sd_block, "request_response_delay_ms"); if (delay > 0) config.sd.request_response_delay_ms = delay;
            int timeout = ExtractInt(sd_block, "request_timeout_ms"); if (timeout > 0) config.sd.request_timeout_ms = timeout;
        }
        
        config.ip = ExtractString(block, "ip");
        if (config.ip.empty()) config.ip = "127.0.0.1";
        
        config.ip_v6 = ExtractString(block, "ip_v6");
        if (config.ip_v6.empty()) config.ip_v6 = "::1";
        
        config.ip_version = ExtractInt(block, "ip_version");
        if (config.ip_version == 0) config.ip_version = 4;

        return config;
    }

private:
    static void ParseProviding(const std::string& json, std::map<std::string, ServiceConfig>& map) {
        size_t pos = 0;
        while ((pos = json.find("\"", pos)) != std::string::npos) {
            size_t key_end = json.find("\"", pos + 1);
            if (key_end == std::string::npos) break;
            std::string key = json.substr(pos + 1, key_end - pos - 1);
            if (key == "providing" || key == "service_id" || key == "instance_id") { pos = key_end + 1; continue; }
            
            size_t obj_start = json.find("{", key_end);
            if (obj_start == std::string::npos) break;
            size_t obj_end = obj_start + 1; int depth = 1;
            while (depth > 0 && obj_end < json.length()) {
                if (json[obj_end] == '{') depth++;
                else if (json[obj_end] == '}') depth--;
                obj_end++;
            }
            
            std::string val = json.substr(obj_start, obj_end - obj_start);
            ServiceConfig cfg;
            cfg.service_id = ExtractInt(val, "service_id");
            cfg.instance_id = ExtractInt(val, "instance_id");
            cfg.major_version = ExtractInt(val, "major_version");
            cfg.minor_version = ExtractInt(val, "minor_version");
            cfg.endpoint = ExtractString(val, "endpoint");
            cfg.multicast = ExtractString(val, "multicast");
            map[key] = cfg;
            pos = obj_end;
        }
    }

    static void ParseRequired(const std::string& json, std::map<std::string, ClientConfig>& map) {
        size_t pos = 0;
        while ((pos = json.find("\"", pos)) != std::string::npos) {
            size_t key_end = json.find("\"", pos + 1);
            if (key_end == std::string::npos) break;
            std::string key = json.substr(pos + 1, key_end - pos - 1);
            
            size_t obj_start = json.find("{", key_end);
            if (obj_start == std::string::npos) break;
            size_t obj_end = obj_start + 1; int depth = 1;
            while (depth > 0 && obj_end < json.length()) {
                if (json[obj_end] == '{') depth++;
                else if (json[obj_end] == '}') depth--;
                obj_end++;
            }
            
            std::string val = json.substr(obj_start, obj_end - obj_start);
            ClientConfig cfg;
            cfg.service_id = ExtractInt(val, "service_id");
            cfg.instance_id = ExtractInt(val, "instance_id");
            cfg.major_version = ExtractInt(val, "major_version");
            cfg.minor_version = ExtractInt(val, "minor_version");
            cfg.endpoint = ExtractString(val, "endpoint");
            map[key] = cfg;
            pos = obj_end;
        }
    }

    static void ParseEndpoints(const std::string& json, std::map<std::string, EndpointConfig>& map) {
        size_t pos = 0;
        while ((pos = json.find("\"", pos)) != std::string::npos) {
            size_t key_end = json.find("\"", pos + 1);
            if (key_end == std::string::npos) break;
            std::string key = json.substr(pos + 1, key_end - pos - 1);
            
            size_t obj_start = json.find("{", key_end);
            if (obj_start == std::string::npos) break;
            size_t obj_end = obj_start + 1; int depth = 1;
            while (depth > 0 && obj_end < json.length()) {
                if (json[obj_end] == '{') depth++;
                else if (json[obj_end] == '}') depth--;
                obj_end++;
            }
            
            std::string val = json.substr(obj_start, obj_end - obj_start);
            EndpointConfig cfg;
            cfg.ip = ExtractString(val, "ip");
            cfg.interface = ExtractString(val, "interface");
            cfg.version = ExtractInt(val, "version");
            cfg.port = ExtractInt(val, "port");
            std::string proto = ExtractString(val, "protocol"); if (!proto.empty()) cfg.protocol = proto;
            map[key] = cfg;
            pos = obj_end;
        }
    }

    static int ExtractInt(const std::string& json, const std::string& key) {
        size_t pos = json.find("\"" + key + "\"");
        if (pos == std::string::npos) return 0;
        size_t colon = json.find(":", pos);
        size_t val_start = json.find_first_not_of(" \t\n\r", colon + 1);
        size_t val_end = json.find_first_of(",}", val_start);
        std::string num = json.substr(val_start, val_end - val_start);
        try { return std::stoi(num, nullptr, 0); } catch(...) { return 0; }
    }
    
    static bool ExtractBool(const std::string& json, const std::string& key) {
        size_t key_pos = json.find("\"" + key + "\"");
        if (key_pos == std::string::npos) return false;
        size_t colon_pos = json.find(":", key_pos);
        if (colon_pos == std::string::npos) return false;
        size_t val_start = json.find_first_not_of(" \t\n\r", colon_pos + 1);
        if (val_start == std::string::npos) return false;
        if (json.substr(val_start, 4) == "true") return true;
        return false;
    }

    static std::string ExtractString(const std::string& json, const std::string& key) {
        size_t pos = json.find("\"" + key + "\"");
        if (pos == std::string::npos) return "";
        size_t colon = json.find(":", pos);
        size_t quote_start = json.find("\"", colon);
        size_t quote_end = json.find("\"", quote_start + 1);
        return json.substr(quote_start + 1, quote_end - quote_start - 1);
    }
};

} // namespace fusion_hawking
