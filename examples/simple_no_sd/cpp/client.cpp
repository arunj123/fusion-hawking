#include <iostream>
#include <vector>
#include <cstring>

#ifdef _WIN32
#include <winsock2.h>
#pragma comment(lib, "ws2_32.lib")
#define SOCKLEN_T int
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#define SOCKLEN_T socklen_t
typedef int SOCKET;
#define closesocket close
#endif

int main() {
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif

    SOCKET sock = socket(AF_INET, SOCK_DGRAM, 0);
    
    // Target: C++ Server on 40002
    sockaddr_in target = {0};
    target.sin_family = AF_INET;
    target.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    target.sin_port = htons(40002);

    // Build Request
    // [Sid:2][Mid:2][Len:4][Cid:2][Sid:2][Pv][Iv][Mt][Rc]
    std::vector<uint8_t> req = {
        0x12, 0x34, // SID
        0x00, 0x01, // MID
        0x00, 0x00, 0x00, 0x0D, // Length (5 payload + 8) = 13 (0x0D)
        0xDE, 0xAD, // CID
        0xBE, 0xEF, // SID
        0x01, 0x01, // Ver
        0x00, 0x00  // Type, RC
    };
    std::string p = "Hello";
    req.insert(req.end(), p.begin(), p.end());

    std::cout << "Sending Request to 127.0.0.1:40002" << std::endl;
    sendto(sock, (const char*)req.data(), (int)req.size(), 0, (struct sockaddr*)&target, sizeof(target));

    char buf[1500];
    sockaddr_in src;
    SOCKLEN_T len = sizeof(src);
    
    // Simple receive with timeout logic omitted for brevity (blocking)
    int bytes = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr*)&src, &len);
    if (bytes >= 16) {
        if (buf[14] == 0x80) {
            std::cout << "Success: Got Response!" << std::endl;
            if (bytes > 16) {
                std::string s(buf + 16, buf + bytes);
                std::cout << "Payload: " << s << std::endl;
            }
        }
    }

#ifdef _WIN32
    closesocket(sock);
    WSACleanup();
#endif
    return 0;
}
