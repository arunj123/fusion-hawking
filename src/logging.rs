use std::sync::Arc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogLevel {
    Debug,
    Info,
    Warn,
    Error,
}

pub trait FusionLogger: Send + Sync {
    fn log(&self, level: LogLevel, component: &str, msg: &str);
}

pub struct ConsoleLogger;

impl ConsoleLogger {
    pub fn new() -> Arc<Self> {
        Arc::new(Self)
    }
}

impl FusionLogger for ConsoleLogger {
    fn log(&self, level: LogLevel, component: &str, msg: &str) {
        let level_str = match level {
            LogLevel::Debug => "DEBUG",
            LogLevel::Info => "INFO ",
            LogLevel::Warn => "WARN ",
            LogLevel::Error => "ERROR",
        };
        // Timestamp using system time (seconds since program start would need static, so using epoch millis % day)
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        let secs = now.as_secs() % 86400; // seconds in day
        let millis = now.subsec_millis();
        let h = secs / 3600;
        let m = (secs % 3600) / 60;
        let s = secs % 60;
        println!("[{:02}:{:02}:{:02}.{:03}] [{}] [{}] {}", h, m, s, millis, level_str, component, msg);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    
    // Mock logger for testing
    struct MockLogger {
        logs: Mutex<Vec<(LogLevel, String, String)>>,
    }
    
    impl MockLogger {
        fn new() -> Arc<Self> {
            Arc::new(Self { logs: Mutex::new(Vec::new()) })
        }
        
        fn get_logs(&self) -> Vec<(LogLevel, String, String)> {
            self.logs.lock().unwrap().clone()
        }
    }
    
    impl FusionLogger for MockLogger {
        fn log(&self, level: LogLevel, component: &str, msg: &str) {
            self.logs.lock().unwrap().push((level, component.to_string(), msg.to_string()));
        }
    }
    
    #[test]
    fn test_log_level_enum() {
        assert_eq!(LogLevel::Debug, LogLevel::Debug);
        assert_ne!(LogLevel::Debug, LogLevel::Info);
        assert_ne!(LogLevel::Warn, LogLevel::Error);
    }
    
    #[test]
    fn test_log_level_debug() {
        let level = LogLevel::Debug;
        assert_eq!(format!("{:?}", level), "Debug");
    }
    
    #[test]
    fn test_console_logger_creation() {
        let logger = ConsoleLogger::new();
        // Just verify creation doesn't panic
        assert!(Arc::strong_count(&logger) == 1);
    }
    
    #[test]
    fn test_console_logger_implements_trait() {
        let logger: Arc<dyn FusionLogger> = ConsoleLogger::new();
        // Should compile and not panic
        logger.log(LogLevel::Info, "TEST", "Hello world");
    }
    
    #[test]
    fn test_mock_logger_captures_logs() {
        let logger = MockLogger::new();
        
        logger.log(LogLevel::Debug, "Component1", "Debug message");
        logger.log(LogLevel::Info, "Component2", "Info message");
        logger.log(LogLevel::Warn, "Component3", "Warning");
        logger.log(LogLevel::Error, "Component4", "Error!");
        
        let logs = logger.get_logs();
        assert_eq!(logs.len(), 4);
        
        assert_eq!(logs[0].0, LogLevel::Debug);
        assert_eq!(logs[0].1, "Component1");
        assert_eq!(logs[0].2, "Debug message");
        
        assert_eq!(logs[1].0, LogLevel::Info);
        assert_eq!(logs[2].0, LogLevel::Warn);
        assert_eq!(logs[3].0, LogLevel::Error);
    }
    
    #[test]
    fn test_log_level_ordering() {
        // Verify all log levels exist and are distinct
        let levels = [LogLevel::Debug, LogLevel::Info, LogLevel::Warn, LogLevel::Error];
        for (i, level) in levels.iter().enumerate() {
            for (j, other) in levels.iter().enumerate() {
                if i == j {
                    assert_eq!(level, other);
                } else {
                    assert_ne!(level, other);
                }
            }
        }
    }
    
    #[test]
    fn test_logger_send_sync() {
        // Verify FusionLogger can be shared across threads
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<ConsoleLogger>();
    }
    
    #[test]
    fn test_empty_component_and_message() {
        let logger = MockLogger::new();
        logger.log(LogLevel::Info, "", "");
        
        let logs = logger.get_logs();
        assert_eq!(logs.len(), 1);
        assert_eq!(logs[0].1, "");
        assert_eq!(logs[0].2, "");
    }
    
    #[test]
    fn test_unicode_in_logs() {
        let logger = MockLogger::new();
        logger.log(LogLevel::Info, "日本語", "Привет мир! 🚀");
        
        let logs = logger.get_logs();
        assert_eq!(logs[0].1, "日本語");
        assert_eq!(logs[0].2, "Привет мир! 🚀");
    }
}
