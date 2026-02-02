import datetime
from enum import Enum

class LogLevel(Enum):
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

class ILogger:
    def log(self, level: LogLevel, component: str, msg: str):
        pass

class ConsoleLogger(ILogger):
    def log(self, level: LogLevel, component: str, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{level.name:5}] [{component}] {msg}")
