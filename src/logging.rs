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
