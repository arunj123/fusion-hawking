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
    std::vector<std::string> interfaces;
    std::map<std::string, std::string> offer_on; // Interface -> Endpoint Name
    uint32_t cycle_offer_ms = 0; // 0 means use global/SD setting
};

struct EndpointConfig {
    std::string iface;
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
    std::string preferred_interface;
    std::vector<std::string> find_on; // List of interface names
};

struct SdConfig {
    uint32_t cycle_offer_ms = 500;
    uint32_t request_response_delay_ms = 50;
    uint32_t request_timeout_ms = 2000;
    uint16_t multicast_hops = 1;
};

struct InterfaceSdConfig {
    std::string endpoint;
    std::string endpoint_v6;
    
    // Legacy/Direct bind support (if needed internally)
    std::string unicast_bind_endpoint; 
};

struct InterfaceConfig {
    std::string name;
    std::map<std::string, EndpointConfig> endpoints;
    InterfaceSdConfig sd;
};

struct InstanceConfig {
    std::string ip;
    std::string ip_v6;
    int ip_version = 4;
    std::string endpoint;
    std::map<std::string, ServiceConfig> providing;
    std::map<std::string, ClientConfig> required;
    std::map<std::string, EndpointConfig> endpoints;
    std::map<std::string, InterfaceConfig> interfaces;
    std::map<std::string, std::string> unicast_bind; // Interface -> Endpoint Name
    SdConfig sd;
    
    // Config helpers (legacy/fallback)
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
        size_t endp_pos = json.find("\"endpoints\":");
        if (endp_pos != std::string::npos) {
             size_t e_start = json.find("{", endp_pos + 12);
             size_t e_end = e_start + 1; int e_depth = 1;
             while (e_depth > 0 && e_end < json.length()) {
                 if (json[e_end] == '{') e_depth++;
                 else if (json[e_end] == '}') e_depth--;
                 e_end++;
             }
             ParseEndpoints(json.substr(e_start, e_end - e_start), config.endpoints);
        }

        // Parse Global SD (Root level)
        size_t global_sd_pos = json.find("\"sd\":");
        if (global_sd_pos != std::string::npos) {
            std::cout << "[ConfigLoader] Found global sd block at " << global_sd_pos << std::endl;
            // Only parse if it's likely a root-level key (avoid parsing instance-level sd here)
            size_t s_start = json.find("{", global_sd_pos + 5);
            size_t s_end = s_start + 1; int s_depth = 1;
            while (s_depth > 0 && s_end < json.length()) {
                if (json[s_end] == '{') s_depth++;
                else if (json[s_end] == '}') s_depth--;
                s_end++;
            }
            std::string sd_block = json.substr(s_start, s_end - s_start);
            int cycle = ExtractInt(sd_block, "cycle_offer_ms"); if (cycle > 0) config.sd.cycle_offer_ms = cycle;
            int delay = ExtractInt(sd_block, "request_response_delay_ms"); if (delay > 0) config.sd.request_response_delay_ms = delay;
            int timeout = ExtractInt(sd_block, "request_timeout_ms"); if (timeout > 0) config.sd.request_timeout_ms = timeout;
            int hops = ExtractInt(sd_block, "multicast_hops"); if (hops > 0) config.sd.multicast_hops = (uint16_t)hops;
            std::cout << "[ConfigLoader] Global SD timeout: " << config.sd.request_timeout_ms << "ms" << std::endl;
        }

        size_t inst_pos = json.find("\"" + instance_name + "\":");
        if (inst_pos == std::string::npos) inst_pos = json.find("\"" + instance_name + "\""); // fallback
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
        
        // Parse unicast_bind
        size_t ub_pos = block.find("\"unicast_bind\"");
        if (ub_pos != std::string::npos) {
            size_t ub_start = block.find("{", ub_pos);
            size_t ub_end = ub_start + 1; int ub_depth = 1;
            while (ub_depth > 0 && ub_end < block.length()) {
                if (block[ub_end] == '{') ub_depth++;
                else if (block[ub_end] == '}') ub_depth--;
                ub_end++;
            }
            ParseStringMap(block.substr(ub_start, ub_end - ub_start), config.unicast_bind);
        }

        size_t prov_pos = block.find("\"providing\":");
        if (prov_pos != std::string::npos) {
            size_t p_start = block.find("{", prov_pos + 12);
            int p_depth = 1; size_t p_end = p_start + 1;
            while (p_depth > 0 && p_end < block.length()) {
                if (block[p_end] == '{') p_depth++;
                else if (block[p_end] == '}') p_depth--;
                p_end++;
            }
            ParseProviding(block.substr(p_start, p_end - p_start), config.providing);
        }

        size_t req_pos = block.find("\"required\":");
        if (req_pos != std::string::npos) {
            size_t r_start = block.find("{", req_pos + 11);
            int r_depth = 1; size_t r_end = r_start + 1;
            while (r_depth > 0 && r_end < block.length()) {
                if (block[r_end] == '{') r_depth++;
                else if (block[r_end] == '}') r_depth--;
                r_end++;
            }
            ParseRequired(block.substr(r_start, r_end - r_start), config.required);
        }

        size_t sd_pos = block.find("\"sd\":");
        if (sd_pos != std::string::npos) {
            std::cout << "[ConfigLoader] Found instance-level sd block for " << instance_name << std::endl;
            size_t sd_start = block.find("{", sd_pos + 5);
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
            int hops = ExtractInt(sd_block, "multicast_hops"); if (hops > 0) config.sd.multicast_hops = (uint16_t)hops;
            std::cout << "[ConfigLoader] Instance SD timeout: " << config.sd.request_timeout_ms << "ms" << std::endl;
        }
        
        config.ip = ExtractString(block, "ip");
        config.ip_v6 = ExtractString(block, "ip_v6");
        config.endpoint = ExtractString(block, "endpoint");
        config.ip_version = ExtractInt(block, "ip_version");

        // 2. Parse Interfaces (Global)
        size_t iface_pos = json.find("\"interfaces\":");
        if (iface_pos != std::string::npos) {
             size_t i_start = json.find("{", iface_pos + 13);
             size_t i_end = i_start + 1; int i_depth = 1;
             while (i_depth > 0 && i_end < json.length()) {
                 if (json[i_end] == '{') i_depth++;
                 else if (json[i_end] == '}') i_depth--;
                 i_end++;
             }
             ParseInterfaces(json.substr(i_start, i_end - i_start), config.interfaces);
        }

        return config;
    }

private:
    static void ParseStringMap(const std::string& json, std::map<std::string, std::string>& map) {
        size_t pos = 0;
        while ((pos = json.find("\"", pos)) != std::string::npos) {
            size_t key_end = json.find("\"", pos + 1);
            if (key_end == std::string::npos) break;
            std::string key = json.substr(pos + 1, key_end - pos - 1);
            
            size_t val_start = json.find(":", key_end);
            if (val_start == std::string::npos) break;
            size_t quote_start = json.find("\"", val_start);
            if (quote_start == std::string::npos) break;
            size_t quote_end = json.find("\"", quote_start + 1);
            if (quote_end == std::string::npos) break;
            
            std::string val = json.substr(quote_start + 1, quote_end - quote_start - 1);
            map[key] = val;
            pos = quote_end + 1;
        }
    }

    static void ParseProviding(const std::string& json, std::map<std::string, ServiceConfig>& map) {
        size_t pos = 0;
        while ((pos = json.find("\"", pos)) != std::string::npos) {
            size_t key_end = json.find("\"", pos + 1);
            if (key_end == std::string::npos) break;
            std::string key = json.substr(pos + 1, key_end - pos - 1);
            if (key == "providing" || key == "service_id" || key == "instance_id" || key == "unicast_bind") { pos = key_end + 1; continue; }
            
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
            cfg.cycle_offer_ms = ExtractInt(val, "cycle_offer_ms");

            size_t iface_arr_pos = val.find("\"interfaces\"");
            if (iface_arr_pos != std::string::npos) {
                size_t arr_start = val.find("[", iface_arr_pos);
                size_t arr_end = val.find("]", arr_start);
                if (arr_start != std::string::npos && arr_end != std::string::npos) {
                    std::string arr_content = val.substr(arr_start + 1, arr_end - arr_start - 1);
                    ParseStringList(arr_content, cfg.interfaces);
                }
            }

            // Parse offer_on
            size_t off_pos = val.find("\"offer_on\"");
            if (off_pos != std::string::npos) {
                size_t off_start = val.find("{", off_pos);
                size_t off_end = off_start + 1; int off_depth = 1;
                while (off_depth > 0 && off_end < val.length()) {
                    if (val[off_end] == '{') off_depth++;
                    else if (val[off_end] == '}') off_depth--;
                    off_end++;
                }
                ParseStringMap(val.substr(off_start, off_end - off_start), cfg.offer_on);
            }

            map[key] = cfg;
            pos = obj_end;
        }
    }

    static void ParseInterfaces(const std::string& json, std::map<std::string, InterfaceConfig>& map) {
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
            InterfaceConfig cfg;
            cfg.name = ExtractString(val, "name");
            
            size_t endp_pos = val.find("\"endpoints\"");
            if (endp_pos != std::string::npos) {
                 size_t e_start = val.find("{", endp_pos);
                 size_t e_end = e_start + 1; int e_depth = 1;
                 while (e_depth > 0 && e_end < val.length()) {
                     if (val[e_end] == '{') e_depth++;
                     else if (val[e_end] == '}') e_depth--;
                     e_end++;
                 }
                 ParseEndpoints(val.substr(e_start, e_end - e_start), cfg.endpoints);
            }
            
            size_t sd_pos = val.find("\"sd\"");
            if (sd_pos != std::string::npos) {
                size_t s_start = val.find("{", sd_pos);
                size_t s_end = s_start + 1; int s_depth = 1;
                while (s_depth > 0 && s_end < val.length()) {
                    if (val[s_end] == '{') s_depth++;
                    else if (val[s_end] == '}') s_depth--;
                    s_end++;
                }
                std::string sd_val = val.substr(s_start, s_end - s_start);
                cfg.sd.endpoint = ExtractString(sd_val, "endpoint_v4");
                if (cfg.sd.endpoint.empty()) cfg.sd.endpoint = ExtractString(sd_val, "endpoint");
                cfg.sd.endpoint_v6 = ExtractString(sd_val, "endpoint_v6");
            }

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
            if (key == "required" || key == "service_id" || key == "instance_id") { pos = key_end + 1; continue; }
            
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
            cfg.preferred_interface = ExtractString(val, "preferred_interface");

            size_t find_pos = val.find("\"find_on\"");
            if (find_pos != std::string::npos) {
                size_t arr_start = val.find("[", find_pos);
                size_t arr_end = val.find("]", arr_start);
                if (arr_start != std::string::npos && arr_end != std::string::npos) {
                    std::string arr_content = val.substr(arr_start + 1, arr_end - arr_start - 1);
                    ParseStringList(arr_content, cfg.find_on);
                }
            }

            map[key] = cfg;
            pos = obj_end;
        }
    }

    static void ParseStringList(const std::string& content, std::vector<std::string>& list) {
        size_t s_pos = 0;
        while ((s_pos = content.find("\"", s_pos)) != std::string::npos) {
            size_t s_end = content.find("\"", s_pos + 1);
            if (s_end == std::string::npos) break;
            list.push_back(content.substr(s_pos + 1, s_end - s_pos - 1));
            s_pos = s_end + 1;
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
            cfg.iface = ExtractString(val, "interface");
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
        size_t val_start = json.find_first_not_of(" \t\n\r\"", colon + 1);
        size_t val_end = json.find_first_of(",} \t\n\r\"", val_start);
        if (val_end == std::string::npos) val_end = json.length();
        std::string num = json.substr(val_start, val_end - val_start);
        try { return std::stoi(num, nullptr, 0); } catch(...) { return 0; }
    }
    
    static bool ExtractBool(const std::string& json, const std::string& key) {
        size_t key_pos = json.find("\"" + key + "\"");
        if (key_pos == std::string::npos) return false;
        size_t colon_pos = json.find(":", key_pos);
        if (colon_pos == std::string::npos) return false;
        size_t val_start = json.find_first_not_of(" \t\n\r\"", colon_pos + 1);
        if (val_start == std::string::npos) return false;
        if (json.substr(val_start, 4) == "true") return true;
        return false;
    }

    static std::string ExtractString(const std::string& json, const std::string& key) {
        size_t pos = json.find("\"" + key + "\"");
        if (pos == std::string::npos) return "";
        size_t colon = json.find(":", pos);
        size_t quote_start = json.find("\"", colon);
        if (quote_start == std::string::npos) return "";
        size_t quote_end = json.find("\"", quote_start + 1);
        if (quote_end == std::string::npos) return "";
        return json.substr(quote_start + 1, quote_end - quote_start - 1);
    }
};

} // namespace fusion_hawking
