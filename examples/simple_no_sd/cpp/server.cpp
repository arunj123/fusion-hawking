#include <iostream>
#include <vector>
#include <cstring>
#include <iomanip>

#ifdef _WIN32
#include <winsock2.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#endif

void print_hex(const std::vector<uint8_t>& data) {
    for (auto b : data) std::cout << std::hex << std::setw(2) << std::setfill('0') << (int)b << " ";
    std::cout << std::dec << std::endl;
}

int main() {
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif

    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK); // 127.0.0.1
    addr.sin_port = htons(40002);

    if (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "Bind failed" << std::endl;
        return 1;
    }

    std::cout << "Simple C++ Server listening on 127.0.0.1:40002" << std::endl;

    char buf[1500];
    while (true) {
        sockaddr_in src;
        int len = sizeof(src);
        int bytes = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, &len);
        
        if (bytes < 16) continue;

        std::cout << "Received " << bytes << " bytes." << std::endl;

        // Parse Header
        uint8_t msg_type = buf[14];
        uint16_t sid = (uint8_t(buf[0]) << 8) | uint8_t(buf[1]);
        
        std::cout << "  Service: 0x" << std::hex << sid << ", Type: 0x" << (int)msg_type << std::dec << std::endl;

        if (msg_type == 0x00) { // Request
            std::cout << "  Sending Response..." << std::endl;
            
            std::vector<uint8_t> res(buf, buf + 16);
            res[14] = 0x80; // MsgType: Response
            res[15] = 0x00; // RC: OK
            
            // Payload "C++ OK"
            std::string payload = "C++ OK";
            uint32_t total_len = payload.size() + 8;
            res[4] = (total_len >> 24) & 0xFF;
            res[5] = (total_len >> 16) & 0xFF;
            res[6] = (total_len >> 8) & 0xFF;
            res[7] = total_len & 0xFF;

            res.insert(res.end(), payload.begin(), payload.end());

            sendto(sock, (const char*)res.data(), res.size(), 0, (struct sockaddr*)&src, len);
        }
    }

#ifdef _WIN32
    closesocket(sock);
    WSACleanup();
#endif
    return 0;
}
