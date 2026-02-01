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
        // Simple timestamp could be added if dependencies allowed, but keeping minimal.
        println!("[{}] [{}] {}", level_str, component, msg);
    }
}
