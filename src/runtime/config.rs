use serde::Deserialize;
use std::collections::HashMap;

#[derive(Debug, Deserialize, Clone)]
pub struct EndpointConfig {
    pub interface: String,
    pub ip: String,
    pub version: u8,
    pub port: u16,
    pub protocol: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct MulticastConfig {
    pub ip: String,
    pub port: u16,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ServiceConfig {
    pub service_id: u16,
    pub instance_id: u16,
    pub major_version: u8,
    #[serde(default)]
    pub minor_version: u32,
    pub endpoint: String,
    pub multicast: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ClientConfig {
    pub service_id: u16,
    pub instance_id: u16,
    pub major_version: u8,
    pub endpoint: Option<String>,
}

/// Service Discovery Configuration
/// All timing values are in milliseconds unless otherwise specified
#[derive(Debug, Deserialize, Clone)]
pub struct SdConfig {
    pub multicast_endpoint: Option<String>,
    pub multicast_endpoint_v6: Option<String>,
    /// Minimum initial delay before first offer (ms, default: 10)
    #[serde(default = "default_initial_delay_min")]
    pub initial_delay_min_ms: u64,
    /// Maximum initial delay before first offer (ms, default: 100)
    #[serde(default = "default_initial_delay_max")]
    pub initial_delay_max_ms: u64,
    /// Base delay for repetition phase (ms, default: 100)
    #[serde(default = "default_repetition_base_delay")]
    pub repetition_base_delay_ms: u64,
    /// Maximum repetitions before entering main phase (default: 3)
    #[serde(default = "default_repetition_max")]
    pub repetition_max: u32,
    /// Cyclic announcement delay in main phase (ms, default: 1000)
    #[serde(default = "default_cyclic_delay")]
    pub cyclic_delay_ms: u64,
    /// Time-to-live for service offers (seconds, default: 0xFFFFFF = ~194 days)
    #[serde(default = "default_ttl")]
    pub ttl: u32,
    /// Request response delay min (ms, default: 10)
    #[serde(default = "default_request_response_delay_min")]
    pub request_response_delay_min_ms: u64,
    /// Request response delay max (ms, default: 100)
    #[serde(default = "default_request_response_delay_max")]
    pub request_response_delay_max_ms: u64,
    /// Request timeout (ms, default: 2000)
    #[serde(default = "default_request_timeout")]
    pub request_timeout_ms: u64,
}

impl Default for SdConfig {
    fn default() -> Self {
        SdConfig {
            multicast_endpoint: None,
            multicast_endpoint_v6: None,
            initial_delay_min_ms: default_initial_delay_min(),
            initial_delay_max_ms: default_initial_delay_max(),
            repetition_base_delay_ms: default_repetition_base_delay(),
            repetition_max: default_repetition_max(),
            cyclic_delay_ms: default_cyclic_delay(),
            ttl: default_ttl(),
            request_response_delay_min_ms: default_request_response_delay_min(),
            request_response_delay_max_ms: default_request_response_delay_max(),
            request_timeout_ms: default_request_timeout(),
        }
    }
}

fn default_initial_delay_min() -> u64 { 10 }
fn default_initial_delay_max() -> u64 { 100 }
fn default_repetition_base_delay() -> u64 { 100 }
fn default_repetition_max() -> u32 { 3 }
fn default_cyclic_delay() -> u64 { 1000 }
fn default_ttl() -> u32 { 0x00FFFFFF }
fn default_request_response_delay_min() -> u64 { 10 }
fn default_request_response_delay_max() -> u64 { 100 }
fn default_request_timeout() -> u64 { 2000 }

#[derive(Debug, Deserialize, Clone)]
pub struct InstanceConfig {
    #[serde(default)]
    pub providing: HashMap<String, ServiceConfig>,
    #[serde(default)]
    pub required: HashMap<String, ClientConfig>,
    /// Service Discovery configuration
    #[serde(default)]
    pub sd: SdConfig,
}

#[derive(Debug, Deserialize, Clone)]
pub struct SystemConfig {
    #[serde(default)]
    pub endpoints: HashMap<String, EndpointConfig>,
    pub instances: HashMap<String, InstanceConfig>,
}
