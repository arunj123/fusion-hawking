use serde::Deserialize;
use std::collections::HashMap;

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
    pub port: Option<u16>,
    pub protocol: Option<String>,
    pub multicast: Option<MulticastConfig>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ClientConfig {
    pub service_id: u16,
    pub instance_id: u16,
    pub major_version: u8,
    pub static_ip: Option<String>,
    pub static_port: Option<u16>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct InstanceConfig {
    pub ip: String,
    #[serde(default)]
    pub providing: HashMap<String, ServiceConfig>,
    #[serde(default)]
    pub required: HashMap<String, ClientConfig>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct SystemConfig {
    pub instances: HashMap<String, InstanceConfig>,
}
