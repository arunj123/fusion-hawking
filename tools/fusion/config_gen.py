import os
import json

def generate_integrated_apps_config(env, output_dir):
    """Generate configuration for Integrated Apps demo based on environment."""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "config.json")
    
    ipv4 = env.primary_ip or "127.0.0.1"
    primary_iface = env.primary_interface or ("Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo")
    
    # Default Config Structure (Mirroring old config.json logic)
    config = {
        "interfaces": {
            "primary": {
                "name": primary_iface,
                "endpoints": {
                    "rust_udp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "udp"},
                    "rust_tcp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "tcp"},
                    "python_tcp": {"ip": "::1" if env.has_ipv6 else ipv4, "version": 6 if env.has_ipv6 else 4, "port": 0, "protocol": "tcp"}, 
                    "python_v4_tcp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "tcp"},
                    "python_v4_udp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "udp"},
                    "cpp_udp": {"ip": ipv4, "version": 4, "port": 0, "protocol": "udp"}, # Was 10.0.1.2 in VNet
                    "js_udp": {"ip": "127.0.0.1", "version": 4, "port": 0, "protocol": "udp"}, # Keep JS on loopback effectively? Or bind to host IP?
                    
                    # SD Endpoints
                    "sd_multicast_v4": {"ip": "224.224.224.245", "port": 30890, "version": 4, "protocol": "udp"},
                    "sd_unicast_v4": {"ip": ipv4, "port": 0, "version": 4, "protocol": "udp"}, # Unicast bind to local IP
                },
                "sd": {
                    "endpoint_v4": "sd_multicast_v4"
                }
            }
        },
        "instances": {
            "rust_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "providing": {
                    "math-service": {"service_id": 4097, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}},
                    "eco-service": {"service_id": 4098, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_tcp"}},
                    "complex-service": {"service_id": 16385, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}}
                },
                "required": {
                    "math-client-v2": {"service_id": 4097, "instance_id": 3, "major_version": 2, "find_on": ["primary"]},
                    "math-client-v1-inst2": {"service_id": 4097, "instance_id": 2, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "diag-client": {"service_id": 20481, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                },
                "sd": {"cycle_offer_ms": 1000}
            },
            "python_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "providing": {
                    "string-service": {"service_id": 8193, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_udp"}},
                    "diagnostic-service": {"service_id": 20481, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_tcp"}}, # Using v4 tcp for simplicity
                    "math-service": {"service_id": 4097, "instance_id": 3, "major_version": 2, "offer_on": {"primary": "python_v4_tcp"}}
                },
                "required": {
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "eco-client": {"service_id": 4098, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "complex-client": {"service_id": 16385, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sensor-client": {"service_id": 24577, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            },
            "cpp_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "providing": {
                    "sort-service": {"service_id": 12289, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "sensor-service": {"service_id": 24577, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "math-service": {"service_id": 4097, "instance_id": 2, "major_version": 1, "offer_on": {"primary": "cpp_udp"}}
                },
                "required": {
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            },
            "js_app_instance": {
                "unicast_bind": {"primary": "sd_unicast_v4"},
                "required": {
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            }
        }
    }

    # IPv6 Support if available
    if env.has_ipv6:
            config["interfaces"]["primary"]["endpoints"]["sd_multicast_v6"] = {"ip": "ff0e::4:C", "port": 31890, "version": 6, "protocol": "udp"}
            config["interfaces"]["primary"]["endpoints"]["sd_unicast_v6"] = {"ip": "::1", "port": 31890, "version": 6, "protocol": "udp"}
            config["interfaces"]["primary"]["sd"]["endpoint_v6"] = "sd_multicast_v6"

    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    
    print(f"  [config] Generated integrated_apps config to: {config_path}")
    return config_path

def generate_automotive_pubsub_config(env, output_dir):
    """Generate configuration for Automotive PubSub demo."""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "config.json")
    
    primary_iface = env.primary_interface or ("Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo")
    ipv4 = "127.0.0.1" # Using Loopback mostly for ADAS
    
    config = {
        "interfaces": {
            "primary": {
                "name": primary_iface,
                "endpoints": {
                    "sd_multicast": {
                        "ip": "224.0.0.4",
                        "port": 30892,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "event_multicast": {
                        "ip": "225.0.0.3",
                        "port": 30895,
                        "version": 4,
                        "protocol": "udp"
                    },
                    "radar_ep": { "ip": ipv4, "port": 0, "version": 4, "protocol": "udp" },
                    "fusion_ep": { "ip": ipv4, "port": 0, "version": 4, "protocol": "udp" },
                    "sd_unicast_ep": { "ip": ipv4, "port": 0, "version": 4, "protocol": "udp" }
                },
                "sd": {
                    "endpoint": "sd_multicast"
                }
            }
        },
        "instances": {
            "radar_cpp_instance": {
                "unicast_bind": { "primary": "sd_unicast_ep" },
                "providing": {
                    "radar-service": {
                        "service_id": 28673, "instance_id": 1, "major_version": 1, "minor_version": 0,
                        "offer_on": { "primary": "radar_ep" },
                        "eventgroups": {
                            "radar-events": {
                                "eventgroup_id": 1,
                                "events": [32769],
                                "multicast": { "primary": "event_multicast" }
                            }
                        }
                    }
                },
                "sd": { "cycle_offer_ms": 1000 }
            },
            "fusion_rust_instance": {
                "unicast_bind": { "primary": "sd_unicast_ep" },
                "providing": {
                    "fusion-service": {
                        "service_id": 28674, "instance_id": 1, "major_version": 1, "minor_version": 0,
                        "offer_on": { "primary": "fusion_ep" },
                        "eventgroups": {
                            "fusion-events": {
                                "eventgroup_id": 1,
                                "events": [32769],
                                "multicast": { "primary": "event_multicast" }
                            }
                        }
                    }
                },
                "required": {
                    "radar-client": {
                        "service_id": 28673, "instance_id": 1, "major_version": 1,
                        "find_on": ["primary"]
                    }
                },
                "sd": { "cycle_offer_ms": 1000 }
            },
            "adas_python_instance": {
                "unicast_bind": { "primary": "sd_unicast_ep" },
                "required": {
                    "fusion-client": {
                        "service_id": 28674, "instance_id": 1, "major_version": 1,
                        "find_on": ["primary"]
                    }
                }
            }
        }
    }
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    return config_path

def generate_someipy_demo_config(env, output_dir):
    """Generate configurations for someipy demo (client_config.json)"""
    os.makedirs(output_dir, exist_ok=True)
    config_path = os.path.join(output_dir, "client_config.json")
    
    ipv4 = "127.0.0.1"
    primary_iface = env.primary_interface or ("Loopback Pseudo-Interface 1" if os.name == 'nt' else "lo")
    
    config = {
        "interfaces": {
            "default": {
                "name": primary_iface,
                "endpoints": {
                    "python_client_ep": { "ip": ipv4, "port": 0, "protocol": "udp", "version": 4 },
                    "cpp_client_ep": { "ip": ipv4, "port": 0, "protocol": "udp", "version": 4 },
                    "rust_client_ep": { "ip": ipv4, "port": 0, "protocol": "udp", "version": 4 },
                    "js_client_ep": { "ip": ipv4, "port": 0, "protocol": "udp", "version": 4 },
                    "sd_multicast": { "ip": "224.0.0.3", "port": 30890, "protocol": "udp", "version": 4 }
                },
                "sd": {
                    "endpoint_v4": "sd_multicast"
                }
            }
        },
        "instances": {
            "python_client": {
                "unicast_bind": { "default": "python_client_ep" },
                "required": {
                    "someipy_svc": { "service_id": 4660, "instance_id": 1, "major_version": 1, "find_on": ["default"] }
                }
            },
            "cpp_client": {
                "unicast_bind": { "default": "cpp_client_ep" },
                "required": {
                    "someipy_svc": { "service_id": 4660, "instance_id": 1, "major_version": 1, "find_on": ["default"] }
                }
            },
            "rust_client": {
                "unicast_bind": { "default": "rust_client_ep" },
                "required": {
                    "someipy_svc": { "service_id": 4660, "instance_id": 1, "major_version": 1, "find_on": ["default"] }
                }
            },
            "js_client": {
                "unicast_bind": { "default": "js_client_ep" },
                "required": {
                    "someipy_svc": { "service_id": 4660, "instance_id": 1, "major_version": 1, "find_on": ["default"] }
                }
            }
        }
    }

    if env.has_ipv6:
        config["interfaces"]["default"]["endpoints"]["sd_multicast_v6"] = { "ip": "ff0e::1", "port": 30890, "protocol": "udp", "version": 6 }
        config["interfaces"]["default"]["endpoints"]["ipv6_unicast"] = { "ip": "::1", "port": 0, "protocol": "udp", "version": 6 }
        config["interfaces"]["default"]["sd"]["endpoint_v6"] = "sd_multicast_v6"
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    
    return config_path
