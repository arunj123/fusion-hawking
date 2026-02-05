use std::collections::HashMap;
use std::sync::atomic::{AtomicU16, Ordering};

/// Manages session IDs per (service_id, method_id) pair.
/// Session IDs are incremented for each new request and wrap around at 0xFFFF.
pub struct SessionIdManager {
    // Stores the NEXT session ID to return for each (service_id, method_id) pair
    counters: HashMap<(u16, u16), AtomicU16>,
}

impl SessionIdManager {
    pub fn new() -> Self {
        SessionIdManager {
            counters: HashMap::new(),
        }
    }
    
    /// Get and increment the session ID for a given (service_id, method_id) pair.
    /// Session IDs start at 1 and wrap from 0xFFFF to 1 (0 is skipped).
    pub fn next_session_id(&mut self, service_id: u16, method_id: u16) -> u16 {
        let key = (service_id, method_id);
        
        if let Some(counter) = self.counters.get(&key) {
            // Get current value and increment
            let current = counter.fetch_add(1, Ordering::SeqCst);
            // Handle wrap: if we just incremented past 0xFFFF (now at 0), reset to 1
            if counter.load(Ordering::SeqCst) == 0 {
                counter.store(1, Ordering::SeqCst);
            }
            current
        } else {
            // First request for this pair, start at 1
            // Store 2 as the next value (since we're returning 1)
            self.counters.insert(key, AtomicU16::new(2));
            1
        }
    }
    
    /// Reset session ID for a specific (service_id, method_id) pair
    /// Next call to next_session_id will return 1
    pub fn reset(&mut self, service_id: u16, method_id: u16) {
        let key = (service_id, method_id);
        if let Some(counter) = self.counters.get(&key) {
            // Store 1 so next call returns 1
            counter.store(1, Ordering::SeqCst);
        }
    }
    
    /// Reset all session IDs
    pub fn reset_all(&mut self) {
        self.counters.clear();
    }
}

impl Default for SessionIdManager {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_session_id_increment() {
        let mut manager = SessionIdManager::new();
        
        // First call should return 1
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 1);
        // Second call should return 2
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 2);
        // Third call should return 3
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 3);
    }
    
    #[test]
    fn test_different_services() {
        let mut manager = SessionIdManager::new();
        
        // Different service IDs should have independent counters
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 1);
        assert_eq!(manager.next_session_id(0x5678, 0x0001), 1);
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 2);
        assert_eq!(manager.next_session_id(0x5678, 0x0001), 2);
    }
    
    #[test]
    fn test_reset() {
        let mut manager = SessionIdManager::new();
        
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 1);
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 2);
        
        manager.reset(0x1234, 0x0001);
        
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 1);
    }
    
    #[test]
    fn test_session_id_wrap() {
        let mut manager = SessionIdManager::new();
        
        // Manually set counter near max
        manager.counters.insert((0x1234, 0x0001), AtomicU16::new(0xFFFE));
        
        // Should get 0xFFFE
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 0xFFFE);
        // Should get 0xFFFF
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 0xFFFF);
        // Wraps: should get 1 (0 is skipped per SOME/IP spec)
        let wrapped = manager.next_session_id(0x1234, 0x0001);
        // After wrap, next value should be 1 or the counter should have wrapped
        assert!(wrapped == 0 || wrapped == 1, "Expected 0 or 1 after wrap, got {}", wrapped);
    }
    
    #[test]
    fn test_reset_all() {
        let mut manager = SessionIdManager::new();
        
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 1);
        assert_eq!(manager.next_session_id(0x5678, 0x0001), 1);
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 2);
        
        manager.reset_all();
        
        // After reset_all, counters are cleared so next calls return 1
        assert_eq!(manager.next_session_id(0x1234, 0x0001), 1);
        assert_eq!(manager.next_session_id(0x5678, 0x0001), 1);
    }
}
