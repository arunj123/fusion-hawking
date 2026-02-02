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
    uint16_t port = 0;
};

struct ClientConfig {
    uint16_t service_id = 0;
    uint16_t instance_id = 1;
    std::string static_ip;
    uint16_t static_port = 0;
};

struct InstanceConfig {
    std::string ip;
    int ip_version = 4;
    std::map<std::string, ServiceConfig> providing;
    std::map<std::string, ClientConfig> required;
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
            cfg.port = ExtractInt(val, "port");
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
            cfg.static_ip = ExtractString(val, "static_ip");
            cfg.static_port = ExtractInt(val, "static_port");
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
        try { return std::stoi(num); } catch(...) { return 0; }
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
