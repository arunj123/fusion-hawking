#pragma once
#include <string>
#include <iostream>
#include <memory>

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
        std::cout << "[" << levelStr << "] [" << component << "] " << msg << std::endl;
    }
};
