#pragma once
#include <string>
#include <iostream>
#include <memory>
#include <chrono>
#include <iomanip>

enum class LogLevel {
    DEBUG,
    INFO,
    WARN,
    ERR
};

class ILogger {
public:
    virtual ~ILogger() = default;
    virtual void Log(LogLevel level, const std::string& component, const std::string& msg) = 0;
};

class ConsoleLogger : public ILogger {
public:
    void Log(LogLevel level, const std::string& component, const std::string& msg) override {
        std::string levelStr;
        switch (level) {
            case LogLevel::DEBUG: levelStr = "DEBUG"; break;
            case LogLevel::INFO:  levelStr = "INFO "; break;
            case LogLevel::WARN:  levelStr = "WARN "; break;
            case LogLevel::ERR:   levelStr = "ERROR"; break;
        }
        // Timestamp
        auto now = std::chrono::system_clock::now();
        auto time = std::chrono::system_clock::to_time_t(now);
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
        std::tm tm_buf;
#ifdef _WIN32
        localtime_s(&tm_buf, &time);
#else
        localtime_r(&time, &tm_buf);
#endif
        std::cout << "[" << std::put_time(&tm_buf, "%H:%M:%S") << "." << std::setfill('0') << std::setw(3) << ms.count() 
                  << "] [" << levelStr << "] [" << component << "] " << msg << std::endl;
    }
};

