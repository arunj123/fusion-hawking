#include "../../src/generated/bindings.hpp"
#include <iostream>
#include <vector>
#include <thread>
#include <chrono>
#include <cstring>
#include <algorithm>

// Platform specific socket includes (Windows)
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")

#define MATH_PORT 30501
#define STRING_PORT 30502
#define SORT_PORT 30503

void run_server() {
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
    
    SOCKET conn_socket = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in server;
    server.sin_family = AF_INET;
    server.sin_addr.s_addr = INADDR_ANY;
    server.sin_port = htons(SORT_PORT);
    
    if (bind(conn_socket, (sockaddr*)&server, sizeof(server)) == SOCKET_ERROR) {
        std::cerr << "Bind failed with error: " << WSAGetLastError() << std::endl;
        return;
    }
    
    std::cout << "C++ Sort Service listening on " << SORT_PORT << "..." << std::endl;
    
    char buf[1500];
    sockaddr_in client;
    int clientLen = sizeof(client);
    
    while(true) {
        int recv_len = recvfrom(conn_socket, buf, 1500, 0, (sockaddr*)&client, &clientLen);
        if (recv_len > 16) {
            // Header Parsing (Naive)
            uint16_t service_id = (buf[0] << 8) | buf[1];
            uint16_t method_id = (buf[2] << 8) | buf[3];
            
            // Sort Service 0x3001
            if (service_id == 0x3001 && method_id == 0x0001) {
                // Parse Payload (Method, Data)
                // CppSortRequest: method:int, data:Vec<int>
                int offset = 16;
                
                // Read int method
                int method = (buf[offset] << 24) | (buf[offset+1] << 16) | (buf[offset+2] << 8) | buf[offset+3];
                offset += 4;
                
                // Read Vec<int>
                uint32_t vec_byte_len = (buf[offset] << 24) | (buf[offset+1] << 16) | (buf[offset+2] << 8) | buf[offset+3];
                offset += 4;
                
                std::vector<int> data;
                int count = vec_byte_len / 4;
                for(int i=0; i<count; i++) {
                     int val = (buf[offset] << 24) | (buf[offset+1] << 16) | (buf[offset+2] << 8) | buf[offset+3];
                     data.push_back(val);
                     offset += 4;
                }
                
                std::cout << "C++ Service received sort req method=" << method << " size=" << data.size() << std::endl;
                
                // Sort
                if (method == 1) std::sort(data.begin(), data.end());
                else std::sort(data.rbegin(), data.rend());
                
                // Response
                CppSortResponse resp;
                resp.sorted_data = data;
                std::vector<uint8_t> payload = resp.serialize(); // Need to implement serialize in generated binding properly
                // But wait, the generated C++ serialize was a placeholder.
                // MANUAL SERIALIZATION for Demo
                std::vector<uint8_t> manual_payload;
                // serialize vector
                 // length
                uint32_t len = data.size() * 4;
                manual_payload.push_back(len >> 24); manual_payload.push_back(len >> 16); manual_payload.push_back(len >> 8); manual_payload.push_back(len);
                for(int val : data) {
                     manual_payload.push_back(val >> 24); manual_payload.push_back(val >> 16); manual_payload.push_back(val >> 8); manual_payload.push_back(val);
                }
                
                // Send Response
                 std::vector<uint8_t> res_msg;
                 // Header
                 res_msg.push_back(service_id >> 8); res_msg.push_back(service_id);
                 res_msg.push_back(method_id >> 8); res_msg.push_back(method_id);
                 uint32_t total_len = manual_payload.size() + 8;
                 res_msg.push_back(total_len >> 24); res_msg.push_back(total_len >> 16); res_msg.push_back(total_len >> 8); res_msg.push_back(total_len);
                 // Client/Session
                 res_msg.push_back(buf[8]); res_msg.push_back(buf[9]); res_msg.push_back(buf[10]); res_msg.push_back(buf[11]);
                 res_msg.push_back(0x01); res_msg.push_back(0x01); res_msg.push_back(0x80); res_msg.push_back(0x00);
                 
                 res_msg.insert(res_msg.end(), manual_payload.begin(), manual_payload.end());
                 
                 sendto(conn_socket, (const char*)res_msg.data(), res_msg.size(), 0, (sockaddr*)&client, clientLen);
            }
        }
    }
}

void send_socket_req(SOCKET s, int port, std::vector<uint8_t>& payload, uint16_t svc, uint16_t method) {
     sockaddr_in dest;
     dest.sin_family = AF_INET;
     dest.sin_port = htons(port);
     inet_pton(AF_INET, "127.0.0.1", &dest.sin_addr);
     
     std::vector<uint8_t> msg;
     msg.push_back(svc >> 8); msg.push_back(svc);
     msg.push_back(method >> 8); msg.push_back(method);
     uint32_t len = payload.size() + 8;
     msg.push_back(len >> 24); msg.push_back(len >> 16); msg.push_back(len >> 8); msg.push_back(len);
     msg.push_back(0x33); msg.push_back(0x33); msg.push_back(0x00); msg.push_back(0x01); // ReqID
     msg.push_back(0x01); msg.push_back(0x01); msg.push_back(0x00); msg.push_back(0x00);
     
     msg.insert(msg.end(), payload.begin(), payload.end());
     
     sendto(s, (const char*)msg.data(), msg.size(), 0, (sockaddr*)&dest, sizeof(dest));
}

void run_client() {
    std::this_thread::sleep_for(std::chrono::seconds(2));
    
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0);
    
    // 1. Call Rust Math (0x1001, 0x0001)
    // Op=3 (Mul), A=6, B=7
    std::vector<uint8_t> p1;
    // Op
    p1.push_back(0); p1.push_back(0); p1.push_back(0); p1.push_back(3);
    // A
    p1.push_back(0); p1.push_back(0); p1.push_back(0); p1.push_back(6);
    // B
    p1.push_back(0); p1.push_back(0); p1.push_back(0); p1.push_back(7);
    
    send_socket_req(s, MATH_PORT, p1, 0x1001, 0x0001);
    std::cout << "C++ Client: Sent Request to Rust Math" << std::endl;
}

int main() {
    std::thread t(run_server);
    t.detach();
    
    run_client();
    
    while(true) std::this_thread::sleep_for(std::chrono::seconds(1));
    return 0;
}
