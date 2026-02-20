"""
Fusion Configuration Generator — Environment-Driven.

The SmartConfigFactory uses NetworkEnvironment to make intelligent choices:
- VNet interfaces preferred when available (for real network isolation)
- IPv6 endpoints added when VNet or host IPv6 is available
- Multicast configured based on actual capability
- Falls back to primary/loopback interfaces on Windows or non-VNet Linux

The low-level ConfigGenerator builder is preserved for custom topologies
(e.g., test_config_usecases.py use-case tests).
"""
import os
import json
import logging

logger = logging.getLogger("fusion.config_gen")


class ConfigGenerator:
    """
    Low-level modular configuration builder for Fusion SOME/IP instances.
    Use this for custom topologies that need manual interface/endpoint control.
    For standard scenarios, prefer SmartConfigFactory.
    """
    def __init__(self):
        self.config = {
            "interfaces": {},
            "instances": {}
        }
        self._global_sd = {}

    def add_interface(self, logical_name, physical_name, endpoints=None, sd=None, server=None):
        """Adds a network interface definition."""
        iface = {
            "name": physical_name,
            "endpoints": {}
        }
        
        if endpoints:
            for name, ep in endpoints.items():
                iface["endpoints"][name] = ep.copy()
                if "protocol" not in iface["endpoints"][name] and "proto" in iface["endpoints"][name]:
                    iface["endpoints"][name]["protocol"] = iface["endpoints"][name].pop("proto")
                if "protocol" not in iface["endpoints"][name]:
                    iface["endpoints"][name]["protocol"] = "udp"
                if "version" not in iface["endpoints"][name]:
                    ip = iface["endpoints"][name].get("ip", "")
                    iface["endpoints"][name]["version"] = 6 if ":" in ip else 4
        if sd:
            iface["sd"] = sd
        if server:
            iface["server"] = server
            
        self.config["interfaces"][logical_name] = iface
        return self

    def add_instance(self, instance_name, unicast_bind=None, providing=None, required=None, sd=None):
        """Adds an application instance definition."""
        inst = {}
        if unicast_bind:
            inst["unicast_bind"] = unicast_bind
        if providing:
            inst["providing"] = providing
        if required:
            inst["required"] = required
        
        # Merge global SD settings with instance-specific ones
        combined_sd = self._global_sd.copy()
        if sd:
            combined_sd.update(sd)
        
        if combined_sd:
            inst["sd"] = combined_sd
            
        self.config["instances"][instance_name] = inst
        return self

    def set_sd(self, request_timeout_ms=None, cycle_offer_ms=None):
        """Sets global SD timing configuration."""
        if request_timeout_ms: self._global_sd["request_timeout_ms"] = request_timeout_ms
        if cycle_offer_ms: self._global_sd["cycle_offer_ms"] = cycle_offer_ms
        return self

    def save(self, path):
        """Saves current configuration to a JSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.config, f, indent=4)
        return path

    def to_dict(self):
        """Returns the config as a dictionary."""
        return self.config


class SmartConfigFactory:
    """
    Environment-aware configuration factory.
    
    Uses NetworkEnvironment to choose interfaces, IPs, and capabilities
    intelligently. Generates configs that work on the detected platform
    without manual patching.
    
    Selection priority:
      1. VNet namespace interfaces (real network isolation)
      2. Host primary interface (eth0, Wi-Fi, etc.)
      3. Loopback interface (last resort, no multicast across nodes)
    """
    
    # Standard SD multicast addresses (consistent across all configs)
    SD_MCAST_V4 = "224.224.224.245"
    SD_MCAST_V4_PORT = 30890
    SD_MCAST_V6 = "ff0e::4:C"
    SD_MCAST_V6_PORT = 31890
    
    # Event multicast for pub/sub demos
    EVENT_MCAST_V4 = "225.0.0.3"
    EVENT_MCAST_V4_PORT = 30895
    
    def __init__(self, env):
        """
        Args:
            env: NetworkEnvironment instance (must have detect() called already)
        """
        self.env = env
    
    def _resolve_interface(self, ns=None):
        """
        Resolve the best interface name and IPs for config generation.
        
        Args:
            ns: Optional namespace name. If provided, uses VNet topology for that ns.
            
        Returns:
            dict: { "name": str, "ipv4": str|None, "ipv6": str|None }
        """
        if ns and self.env.has_vnet:
            # Use VNet namespace interface
            ns_topo = self.env.vnet_topology.get(ns, {})
            # Prefer veth0 (primary VNet interface)
            iface_data = ns_topo.get('veth0', {})
            return {
                "name": "veth0",
                "ipv4": iface_data.get("ipv4"),
                "ipv6": iface_data.get("ipv6"),
            }
        
        if self.env.has_vnet:
            # VNet available but no specific namespace — prefer ns_ecu1 for consistency
            # This ensures single-interface configs (like integrated_apps) use a predictable IP (10.0.1.1)
            # which matches where we run the apps in tests (ns_ecu1).
            if 'ns_ecu1' in self.env.vnet_topology:
                ns_topo = self.env.vnet_topology['ns_ecu1']
                iface_data = ns_topo.get('veth0', {})
                if iface_data.get('ipv4'):
                    return {
                        "name": "veth0",
                        "ipv4": iface_data.get("ipv4"),
                        "ipv6": iface_data.get("ipv6"),
                    }
            
            # Fallback: use first available namespace's veth0
            for ns_name, ns_topo in self.env.vnet_topology.items():
                iface_data = ns_topo.get('veth0', {})
                if iface_data.get('ipv4'):
                    return {
                        "name": "veth0",
                        "ipv4": iface_data.get("ipv4"),
                        "ipv6": iface_data.get("ipv6"),
                    }
        
        # Non-VNet: use detected primary interface
        name = self.env.primary_interface or ("Loopback Pseudo-Interface 1" if self.env.os_type == 'Windows' else "lo")
        ipv4 = self.env.primary_ip or "127.0.0.1"
        ipv6 = None
        
        if self.env.primary_interface and self.env.primary_interface in self.env.interfaces:
            v6_list = self.env.interfaces[self.env.primary_interface].get('ip_v6', [])
            if v6_list:
                # Only use non-link-local (global/ULA) IPv6 addresses.
                # Link-local (fe80::) requires scope IDs (%iface) which
                # runtimes don't handle, causing bind EINVAL errors.
                for v6 in v6_list:
                    if not v6.startswith('fe80'):
                        ipv6 = v6
                        break
        
        return {"name": name, "ipv4": ipv4, "ipv6": ipv6}
    
    def _resolve_vnet_interface(self, ns, iface_name='veth0'):
        """
        Resolve a specific VNet namespace interface.
        
        Returns:
            dict: { "name": str, "ipv4": str|None, "ipv6": str|None }
        """
        ns_topo = self.env.vnet_topology.get(ns, {})
        iface_data = ns_topo.get(iface_name, {})
        return {
            "name": iface_name,
            "ipv4": iface_data.get("ipv4"),
            "ipv6": iface_data.get("ipv6"),
        }
    
    def _make_sd_config(self, include_v6=False):
        """Build the SD section for an interface."""
        sd = {"endpoint_v4": "sd_mcast_v4"}
        if include_v6:
            sd["endpoint_v6"] = "sd_mcast_v6"
        return sd
    
    def _make_sd_endpoints(self, bind_ipv4, bind_ipv6=None):
        """
        Generate SD multicast + unicast endpoints.
        
        Returns:
            dict: Endpoint definitions for SD
        """
        eps = {
            "sd_mcast_v4": {"ip": self.SD_MCAST_V4, "port": self.SD_MCAST_V4_PORT, "version": 4, "protocol": "udp"},
            "sd_uc_v4": {"ip": bind_ipv4, "port": 0, "version": 4, "protocol": "udp"},
        }
        if bind_ipv6:
            eps["sd_mcast_v6"] = {"ip": self.SD_MCAST_V6, "port": self.SD_MCAST_V6_PORT, "version": 6, "protocol": "udp"}
            eps["sd_uc_v6"] = {"ip": bind_ipv6, "port": 0, "version": 6, "protocol": "udp"}
        return eps
    
    def _should_include_ipv6(self):
        """Determine if IPv6 endpoints should be generated."""
        if self.env.has_vnet and self.env.vnet_has_ipv6:
            return True
        return self.env.has_ipv6
    
    def _make_endpoint(self, ip, port=0, protocol="udp"):
        """Create a single endpoint definition."""
        return {
            "ip": ip,
            "port": port,
            "protocol": protocol,
            "version": 6 if ":" in ip else 4,
        }
    
    # ─────────────────────────────────────────────────────────
    #  Standard Config Generators
    # ─────────────────────────────────────────────────────────
    
    def generate_integrated_apps(self, output_dir):
        """
        Generate configuration for the Integrated Apps demo.
        
        Topology:
        - VNet (Distributed): 3 separate configs for ns_ecu1, ns_ecu2, ns_ecu3.
          Returns: output_dir (str)
        - Non-VNet: Single interface (primary).
          Returns: config_path (str)
        """
        gen = ConfigGenerator()
        include_v6 = self._should_include_ipv6()
        
        # Check if we can do a distributed VNet setup
        dist_vnet = False
        if self.env.has_vnet:
            # Check availability of required namespaces
            ecu1 = self._resolve_interface('ns_ecu1')
            ecu2 = self._resolve_interface('ns_ecu2')
            ecu3 = self._resolve_interface('ns_ecu3')
            
            if ecu1['ipv4'] and ecu2['ipv4'] and ecu3['ipv4']:
                dist_vnet = True
                
        if dist_vnet:
            # --- Distributed VNet Configuration (Split Configs) ---
            
            # Rules: We use logical name "primary" for the main interface in EVERY config.
            # This ensures demo apps can hardcode "primary" and work everywhere.
            
            # --- ECU1 (Rust) ---
            gen1 = ConfigGenerator()
            ep1 = {}
            ep1.update(self._make_sd_endpoints(ecu1['ipv4'], ecu1.get('ipv6') if include_v6 else None))
            if "sd_uc_v4" in ep1: ep1["sd_uc_v4"]["port"] = 30490
            # Rust endpoints
            ep1["rust_udp"] = self._make_endpoint(ecu1['ipv4'], 0, "udp")
            ep1["rust_tcp"] = self._make_endpoint(ecu1['ipv4'], 0, "tcp")
            
            gen1.add_interface("primary", ecu1["name"], endpoints=ep1, sd=self._make_sd_config(include_v6=bool(ecu1.get('ipv6') if include_v6 else None)))
            
            gen1.add_instance("rust_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "math-service": {"service_id": 4097, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}},
                    "eco-service": {"service_id": 4098, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_tcp"}},
                    "complex-service": {"service_id": 16385, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}},
                },
                required={
                    "math-client-v2": {"service_id": 4097, "instance_id": 3, "major_version": 2, "find_on": ["primary"]},
                    "math-client-v1-inst2": {"service_id": 4097, "instance_id": 2, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "diag-client": {"service_id": 20481, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                },
                sd={"cycle_offer_ms": 1000}
            )
            gen1.save(os.path.join(output_dir, "config_ecu1.json"))
            
            # --- ECU2 (C++) ---
            gen2 = ConfigGenerator()
            ep2 = {}
            ep2.update(self._make_sd_endpoints(ecu2['ipv4'], ecu2.get('ipv6') if include_v6 else None))
            if "sd_uc_v4" in ep2: ep2["sd_uc_v4"]["port"] = 30490
            # C++ endpoints
            ep2["cpp_udp"] = self._make_endpoint(ecu2['ipv4'], 0, "udp")
            
            gen2.add_interface("primary", ecu2["name"], endpoints=ep2, sd=self._make_sd_config(include_v6=bool(ecu2.get('ipv6') if include_v6 else None)))
            
            gen2.add_instance("cpp_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "sort-service": {"service_id": 12289, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "sensor-service": {"service_id": 24577, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "math-service": {"service_id": 4097, "instance_id": 2, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                },
                required={
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                }
            )
            gen2.save(os.path.join(output_dir, "config_ecu2.json"))
            
            # --- ECU3 (Python) ---
            gen3 = ConfigGenerator()
            ep3 = {}
            ep3.update(self._make_sd_endpoints(ecu3['ipv4'], ecu3.get('ipv6') if include_v6 else None))
            if "sd_uc_v4" in ep3: ep3["sd_uc_v4"]["port"] = 30490
            # Python endpoints
            ep3["python_v4_udp"] = self._make_endpoint(ecu3['ipv4'], 0, "udp")
            ep3["python_v4_tcp"] = self._make_endpoint(ecu3['ipv4'], 0, "tcp")
            if include_v6 and ecu3.get('ipv6'):
                ep3["python_v6_udp"] = self._make_endpoint(ecu3['ipv6'], 0, "udp")
                ep3["python_v6_tcp"] = self._make_endpoint(ecu3['ipv6'], 0, "tcp")

            gen3.add_interface("primary", ecu3["name"], endpoints=ep3, sd=self._make_sd_config(include_v6=bool(ecu3.get('ipv6') if include_v6 else None)))
            
            gen3.add_instance("python_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "string-service": {"service_id": 8193, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_udp"}},
                    "diagnostic-service": {"service_id": 20481, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_tcp"}},
                    "math-service": {"service_id": 4097, "instance_id": 3, "major_version": 2, "offer_on": {"primary": "python_v4_tcp"}},
                },
                required={
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "eco-client": {"service_id": 4098, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "complex-client": {"service_id": 16385, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sensor-client": {"service_id": 24577, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                }
            )
            
            gen3.add_instance("adas_python_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                required={
                    "fusion-client": {"service_id": 28674, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            )
            
            gen3.add_instance("js_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                required={
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "diag-client": {"service_id": 20481, "instance_id": 1, "major_version": 1, "find_on": ["primary"], "protocol": "tcp"},
                    "math-client-tcp": {"service_id": 4097, "instance_id": 3, "major_version": 2, "find_on": ["primary"], "protocol": "tcp"},
                }
            )
            
            gen3.save(os.path.join(output_dir, "config_ecu3.json"))
            logger.info("Generated distributed configs (ecu1,ecu2,ecu3) in " + output_dir)
            return output_dir

        else:
            # --- Single Interface Configuration (Legacy/Loopsback) ---
            iface = self._resolve_interface()
            ipv4 = iface["ipv4"] or "127.0.0.1"
            ipv6 = iface.get("ipv6") if include_v6 else None
            
            # Build endpoints
            endpoints = {
                "rust_udp":     self._make_endpoint(ipv4, 0, "udp"),
                "rust_tcp":     self._make_endpoint(ipv4, 0, "tcp"),
                "python_v4_tcp": self._make_endpoint(ipv4, 0, "tcp"),
                "python_v4_udp": self._make_endpoint(ipv4, 0, "udp"),
                "cpp_udp":      self._make_endpoint(ipv4, 0, "udp"),
                "js_udp":       self._make_endpoint(ipv4, 0, "udp"),
            }
            
            # SD endpoints
            endpoints.update(self._make_sd_endpoints(ipv4, ipv6))
            
            # IPv6 service endpoints (when available)
            if ipv6:
                endpoints["python_v6_tcp"] = self._make_endpoint(ipv6, 0, "tcp")
            
            sd = self._make_sd_config(include_v6=bool(ipv6))
            gen.add_interface("primary", iface["name"], endpoints=endpoints, sd=sd)
            
            # Instances — service topology mirrors the demo architecture
            gen.add_instance("rust_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "math-service": {"service_id": 4097, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}},
                    "eco-service": {"service_id": 4098, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_tcp"}},
                    "complex-service": {"service_id": 16385, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "rust_udp"}},
                },
                required={
                    "math-client-v2": {"service_id": 4097, "instance_id": 3, "major_version": 2, "find_on": ["primary"]},
                    "math-client-v1-inst2": {"service_id": 4097, "instance_id": 2, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "diag-client": {"service_id": 20481, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                },
                sd={"cycle_offer_ms": 1000}
            )
            
            gen.add_instance("python_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "string-service": {"service_id": 8193, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_udp"}},
                    "diagnostic-service": {"service_id": 20481, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_v4_tcp"}},
                    "math-service": {"service_id": 4097, "instance_id": 3, "major_version": 2, "offer_on": {"primary": "python_v4_tcp"}},
                },
                required={
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "eco-client": {"service_id": 4098, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "complex-client": {"service_id": 16385, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sort-client": {"service_id": 12289, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "sensor-client": {"service_id": 24577, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                }
            )
            
            gen.add_instance("cpp_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "sort-service": {"service_id": 12289, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "sensor-service": {"service_id": 24577, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                    "math-service": {"service_id": 4097, "instance_id": 2, "major_version": 1, "offer_on": {"primary": "cpp_udp"}},
                },
                required={
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                }
            )
            
            gen.add_instance("js_app_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                required={
                    "math-client": {"service_id": 4097, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "string-client": {"service_id": 8193, "instance_id": 1, "major_version": 1, "find_on": ["primary"]},
                    "diag-client": {"service_id": 20481, "instance_id": 1, "major_version": 1, "find_on": ["primary"], "protocol": "tcp"},
                    "math-client-tcp": {"service_id": 4097, "instance_id": 3, "major_version": 2, "find_on": ["primary"], "protocol": "tcp"},
                }
            )
        
        config_path = os.path.join(output_dir, "config.json")
        gen.save(config_path)
        logger.info(f"Generated integrated_apps config: {config_path} (iface={iface['name']}, ipv4={ipv4}, ipv6={ipv6})")
        return config_path

    def generate_automotive_pubsub(self, output_dir):
        """
        Generate configuration for Automotive PubSub demo.
        Uses multicast event groups for sensor data distribution.
        
        Topology:
        - VNet (Distributed):
            - Radar on ns_ecu1 -> config_ecu1.json
            - Fusion on ns_ecu2 -> config_ecu2.json
            - ADAS on ns_ecu3 -> config_ecu3.json
        - Non-VNet: Single config for all nodes.
        """
        include_v6 = self._should_include_ipv6()
        
        # Check for distributed VNet capability (Require 3 ECUs)
        dist_vnet = False
        if self.env.has_vnet:
            ecu1 = self._resolve_interface('ns_ecu1')
            ecu2 = self._resolve_interface('ns_ecu2')
            ecu3 = self._resolve_interface('ns_ecu3')
            if ecu1['ipv4'] and ecu2['ipv4'] and ecu3['ipv4']:
                dist_vnet = True
        
        if dist_vnet:
            # --- Distributed Configuration (Split Configs) ---
            ecus = {
                'ecu1': self._resolve_interface('ns_ecu1'),
                'ecu2': self._resolve_interface('ns_ecu2'),
                'ecu3': self._resolve_interface('ns_ecu3')
            }
            
            for name, iface in ecus.items():
                ipv4 = iface["ipv4"]
                ipv6 = iface.get("ipv6") if include_v6 else None
                gen = ConfigGenerator()
                
                endpoints = {
                    "sd_mcast_v4": {"ip": self.SD_MCAST_V4, "port": 30892, "version": 4, "protocol": "udp"},
                    "event_mcast": {"ip": self.EVENT_MCAST_V4, "port": self.EVENT_MCAST_V4_PORT, "version": 4, "protocol": "udp"},
                    "sd_uc_v4":    self._make_endpoint(ipv4, 0, "udp"),
                }
                
                # Add instance-specific endpoints
                if name == 'ecu1':
                    endpoints["radar_ep"] = self._make_endpoint(ecus['ecu1']['ipv4'], 0, "udp")
                elif name == 'ecu2':
                    endpoints["fusion_ep"] = self._make_endpoint(ecus['ecu2']['ipv4'], 0, "udp")
                
                if include_v6:
                    endpoints["sd_mcast_v6"] = {"ip": self.SD_MCAST_V6, "port": 30892, "version": 6, "protocol": "udp"}
                
                sd = {"endpoint_v4": "sd_mcast_v4"}
                if include_v6:
                    sd["endpoint_v6"] = "sd_mcast_v6"
                
                gen.add_interface("primary", iface["name"], endpoints=endpoints, sd=sd)
                
                # Add all instances to all configs (they only run their own)
                # But they need the knowledge of other instances for 'required' blocks
                # Add instance-specific providers only if the endpoint is local
                radar_providing = None
                if name == 'ecu1':
                    radar_providing = {
                        "radar-service": {
                            "service_id": 28673, "instance_id": 1, "major_version": 1, "minor_version": 0,
                            "offer_on": {"primary": "radar_ep"},
                            "eventgroups": {
                                "radar-events": {
                                    "eventgroup_id": 1, "events": [32769], "multicast": {"primary": "event_mcast"}
                                }
                            }
                        }
                    }

                gen.add_instance("radar_cpp_instance",
                    unicast_bind={"primary": "sd_uc_v4"} if name == 'ecu1' else None,
                    providing=radar_providing,
                    sd={"cycle_offer_ms": 1000}
                )
                
                fusion_providing = None
                if name == 'ecu2':
                    fusion_providing = {
                        "fusion-service": {
                            "service_id": 28674, "instance_id": 1, "major_version": 1, "minor_version": 0,
                            "offer_on": {"primary": "fusion_ep"},
                            "eventgroups": {
                                "fusion-events": {
                                    "eventgroup_id": 1, "events": [32769], "multicast": {"primary": "event_mcast"}
                                }
                            }
                        }
                    }

                gen.add_instance("fusion_rust_instance",
                    unicast_bind={"primary": "sd_uc_v4"} if name == 'ecu2' else None,
                    providing=fusion_providing,
                    required={
                        "radar-client": {"service_id": 28673, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                    },
                    sd={"cycle_offer_ms": 1000}
                )
                
                gen.add_instance("adas_python_instance",
                    unicast_bind={"primary": "sd_uc_v4"} if name == 'ecu3' else None,
                    required={
                        "fusion-client": {"service_id": 28674, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                    }
                )
                
                gen.save(os.path.join(output_dir, f"config_{name}.json"))
            
            logger.info(f"Generated split automotive_pubsub configs in {output_dir}")
            return output_dir
        else:
            # --- Single Configuration (Fallback) ---
            iface = self._resolve_interface()
            ipv4 = iface["ipv4"] or "127.0.0.1"
            ipv6 = iface.get("ipv6") if include_v6 else None
            
            gen = ConfigGenerator()
            
            endpoints = {
                "sd_mcast_v4": {"ip": self.SD_MCAST_V4, "port": 30892, "version": 4, "protocol": "udp"},
                "event_mcast": {"ip": self.EVENT_MCAST_V4, "port": self.EVENT_MCAST_V4_PORT, "version": 4, "protocol": "udp"},
                "radar_ep":    self._make_endpoint(ipv4, 0, "udp"),
                "fusion_ep":   self._make_endpoint(ipv4, 0, "udp"),
                "sd_uc_v4":    self._make_endpoint(ipv4, 0, "udp"),
            }
            
            if ipv6:
                endpoints["sd_mcast_v6"] = {"ip": self.SD_MCAST_V6, "port": 30892, "version": 6, "protocol": "udp"}
            
            sd = {"endpoint_v4": "sd_mcast_v4"}
            if ipv6:
                sd["endpoint_v6"] = "sd_mcast_v6"
            
            gen.add_interface("primary", iface["name"], endpoints=endpoints, sd=sd)
            
            gen.add_instance("radar_cpp_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "radar-service": {
                        "service_id": 28673, "instance_id": 1, "major_version": 1, "minor_version": 0,
                        "offer_on": {"primary": "radar_ep"},
                        "eventgroups": {
                            "radar-events": {
                                "eventgroup_id": 1, "events": [32769], "multicast": {"primary": "event_mcast"}
                            }
                        }
                    }
                },
                sd={"cycle_offer_ms": 1000}
            )
            
            gen.add_instance("fusion_rust_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "fusion-service": {
                        "service_id": 28674, "instance_id": 1, "major_version": 1, "minor_version": 0,
                        "offer_on": {"primary": "fusion_ep"},
                        "eventgroups": {
                            "fusion-events": {
                                "eventgroup_id": 1, "events": [32769], "multicast": {"primary": "event_mcast"}
                            }
                        }
                    }
                },
                required={
                    "radar-client": {"service_id": 28673, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                },
                sd={"cycle_offer_ms": 1000}
            )
            
            gen.add_instance("adas_python_instance",
                unicast_bind={"primary": "sd_uc_v4"},
                required={
                    "fusion-client": {"service_id": 28674, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                }
            )
            
            config_path = os.path.join(output_dir, "config.json")
            gen.save(config_path)
            logger.info(f"Generated single automotive_pubsub config: {config_path} (iface={iface['name']}, ipv4={ipv4})")
            return config_path

    def generate_someipy_demo(self, output_dir):
        """
        Generate configuration for someipy interop demo.
        Multi-client scenario: Python, C++, Rust, JS clients talk to Python service (ID 1234).
        
        Topology:
        - VNet (Distributed): 
            - Service on ns_ecu1 (iface_ecu1) -> config_ecu1.json
            - Clients on ns_ecu3 (iface_ecu3) -> config_ecu3.json
            Returns: output_dir
        - Non-VNet: Single interface (primary/loopback) -> client_config.json
            Returns: config_path
        """
        gen = ConfigGenerator().set_sd(request_timeout_ms=5000)
        include_v6 = self._should_include_ipv6()

        # Check for distributed VNet capability
        dist_vnet = False
        if self.env.has_vnet:
            ecu1 = self._resolve_interface('ns_ecu1')
            ecu3 = self._resolve_interface('ns_ecu3')
            if ecu1['ipv4'] and ecu3['ipv4']:
                dist_vnet = True
        
        if dist_vnet:
            # --- Distributed Configuration (Split Configs) ---
            
            # 1. Interface ECU1 (Service)
            gen1 = ConfigGenerator().set_sd(request_timeout_ms=5000)
            ep1 = {}
            ep1.update(self._make_sd_endpoints(ecu1['ipv4'], ecu1.get('ipv6') if include_v6 else None))
            if "sd_uc_v4" in ep1: ep1["sd_uc_v4"]["port"] = 30490
            
            # Service endpoint
            ep1["python_service_udp"] = self._make_endpoint(ecu1['ipv4'], 0, "udp")
            ep1["python_service_tcp"] = self._make_endpoint(ecu1['ipv4'], 0, "tcp")
            
            gen1.add_interface("primary", ecu1["name"], endpoints=ep1, sd=self._make_sd_config(include_v6=bool(ecu1.get('ipv6') if include_v6 else None)))

            # 2. Interface ECU3 (Clients)
            gen3 = ConfigGenerator().set_sd(request_timeout_ms=5000)
            ep3 = {}
            ep3.update(self._make_sd_endpoints(ecu3['ipv4'], ecu3.get('ipv6') if include_v6 else None))
            if "sd_uc_v4" in ep3: ep3["sd_uc_v4"]["port"] = 30490

            # Client endpoints
            ep3["python_client_ep"] = self._make_endpoint(ecu3['ipv4'], 0, "udp")
            ep3["cpp_client_ep"] = self._make_endpoint(ecu3['ipv4'], 0, "udp")
            ep3["rust_client_ep"] = self._make_endpoint(ecu3['ipv4'], 0, "udp")
            ep3["js_client_ep"] = self._make_endpoint(ecu3['ipv4'], 0, "udp")

            gen3.add_interface("primary", ecu3["name"], endpoints=ep3, sd=self._make_sd_config(include_v6=bool(ecu3.get('ipv6') if include_v6 else None)))

            # 3. Instances
            # Python Service (ECU1)
            gen1.add_instance("PythonService",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "someipy_svc": {"service_id": 0x1234, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_service_udp"}}
                },
                sd={"cycle_offer_ms": 1000}
            )
            gen1.save(os.path.join(output_dir, "config_ecu1.json"))

            # Clients (ECU3)
            for client in ["python", "cpp", "rust", "js"]:
                gen3.add_instance(f"{client}_client",
                    unicast_bind={"primary": "sd_uc_v4"},
                    required={
                        "someipy_svc": {"service_id": 0x1234, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                    }
                )
            gen3.save(os.path.join(output_dir, "config_ecu3.json"))
            
            logger.info("Generated distributed someipy_demo configs in " + output_dir)
            return output_dir

        else:
            # --- Single Interface Configuration ---
            iface = self._resolve_interface()
            ipv4 = iface["ipv4"] or "127.0.0.1"
            ipv6 = iface.get("ipv6") if include_v6 else None
            
            endpoints = {
                "python_service_udp": self._make_endpoint(ipv4, 0, "udp"),
                "python_service_tcp": self._make_endpoint(ipv4, 0, "tcp"),
                "python_client_ep": self._make_endpoint(ipv4, 0, "udp"),
                "cpp_client_ep": self._make_endpoint(ipv4, 0, "udp"),
                "rust_client_ep": self._make_endpoint(ipv4, 0, "udp"),
                "js_client_ep": self._make_endpoint(ipv4, 0, "udp"),
            }
            endpoints.update(self._make_sd_endpoints(ipv4, ipv6))

            gen.add_interface("primary", iface["name"], endpoints=endpoints, sd=self._make_sd_config(include_v6=bool(ipv6)))
            
            gen.add_instance("PythonService",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "someipy_svc": {"service_id": 0x1234, "instance_id": 1, "major_version": 1, "offer_on": {"primary": "python_service_udp"}}
                },
                sd={"cycle_offer_ms": 1000}
            )
            
            for client in ["python", "cpp", "rust", "js"]:
                gen.add_instance(f"{client}_client",
                    unicast_bind={"primary": "sd_uc_v4"},
                    required={
                        "someipy_svc": {"service_id": 0x1234, "instance_id": 1, "major_version": 1, "find_on": ["primary"]}
                    }
                )

            config_path = os.path.join(output_dir, "client_config.json")
            gen.save(config_path)
            logger.info(f"Generated someipy_demo config: {config_path}")
            return config_path
    
    def generate_usecase_config(self, usecase, output_dir):
        """
        Generate configuration for VNet use-case tests.
        
        Each use case defines a specific multi-namespace topology.
        This method returns a ConfigGenerator pre-populated with
        the correct VNet IPs and interface names.
        
        Args:
            usecase: Use-case name (e.g., 'multi_homed_provider')
            output_dir: Directory to save config to
            
        Returns:
            (ConfigGenerator, str): The generator (for further customization) and config path
        """
        gen = ConfigGenerator()
        config_path = os.path.join(output_dir, f"{usecase}_config.json")
        return gen, config_path
    
    def generate_large_payload_test(self, output_dir):
        """
        Generate configuration for Large Payload (TP) test.
        
        Topology:
        - VNet (Distributed):
            - Server on ns_ecu1 -> config_server.json
            - Client on ns_ecu2 -> config_client.json
        - Non-VNet:
            - Single config for both -> config.json (or separate if needed)
        """
        include_v6 = self._should_include_ipv6()
        
        # Check for distributed VNet capability
        dist_vnet = False
        if self.env.has_vnet:
            ecu1 = self._resolve_interface('ns_ecu1')
            ecu2 = self._resolve_interface('ns_ecu2')
            if ecu1['ipv4'] and ecu2['ipv4']:
                dist_vnet = True
        
        if dist_vnet:
            # --- Distributed Configuration ---
            ecus = {
                'server': self._resolve_interface('ns_ecu1'),
                'client': self._resolve_interface('ns_ecu2')
            }
            
            for role, iface in ecus.items():
                ipv4 = iface["ipv4"]
                ipv6 = iface.get("ipv6") if include_v6 else None
                gen = ConfigGenerator()
                
                # Endpoints
                # SD Multicast (Standard)
                endpoints = self._make_sd_endpoints(ipv4, ipv6)
                if "sd_uc_v4" in endpoints: endpoints["sd_uc_v4"]["port"] = 30490

                # TP Service Endpoint
                endpoints["tp_endpoint"] = self._make_endpoint(ipv4, 30500, "udp")
                
                gen.add_interface("primary", iface["name"], endpoints=endpoints, sd=self._make_sd_config(include_v6=bool(ipv6)))
                
                if role == 'server':
                    gen.add_instance("tp_server",
                        unicast_bind={"primary": "sd_uc_v4"},
                        providing={
                            "tp_service": {
                                "service_id": 20480, "instance_id": 1, "major_version": 1, "minor_version": 0,
                                "offer_on": {"primary": "tp_endpoint"}
                            }
                        },
                        sd={"cycle_offer_ms": 1000}
                    )
                else: # client
                    gen.add_instance("tp_client",
                        unicast_bind={"primary": "sd_uc_v4"},
                        required={
                            "tp_service": {
                                "service_id": 20480, "instance_id": 1, "major_version": 1, "minor_version": 0,
                                "find_on": ["primary"]
                            }
                        }
                    )
                
                gen.save(os.path.join(output_dir, f"config_{role}.json"))
                
            logger.info(f"Generated distributed large_payload configs in {output_dir}")
            return output_dir

        else:
            # --- Single Host Configuration (Split) ---
            iface = self._resolve_interface()
            ipv4 = iface["ipv4"] or "127.0.0.1"
            ipv6 = iface.get("ipv6") if include_v6 else None
            
            # 1. Server Config
            gen1 = ConfigGenerator()
            ep1 = self._make_sd_endpoints(ipv4, ipv6)
            if "sd_uc_v4" in ep1: ep1["sd_uc_v4"]["port"] = 30490 # Server SD Port
            ep1["tp_endpoint"] = self._make_endpoint(ipv4, 30500, "udp")
            
            gen1.add_interface("primary", iface["name"], endpoints=ep1, sd=self._make_sd_config(include_v6=bool(ipv6)))
            
            gen1.add_instance("tp_server",
                unicast_bind={"primary": "sd_uc_v4"},
                providing={
                    "tp_service": {
                        "service_id": 20480, "instance_id": 1, "major_version": 1, "minor_version": 0,
                        "offer_on": {"primary": "tp_endpoint"}
                    }
                },
                sd={"cycle_offer_ms": 1000}
            )
            gen1.save(os.path.join(output_dir, "config_server.json"))
            
            # 2. Client Config
            gen2 = ConfigGenerator()
            ep2 = self._make_sd_endpoints(ipv4, ipv6)
            # Use DIFFERENT port for Client SD to avoid self-reception on loopback/unicast
            if "sd_uc_v4" in ep2: ep2["sd_uc_v4"]["port"] = 30491 
            
            gen2.add_interface("primary", iface["name"], endpoints=ep2, sd=self._make_sd_config(include_v6=bool(ipv6)))
            
            gen2.add_instance("tp_client",
                unicast_bind={"primary": "sd_uc_v4"},
                required={
                    "tp_service": {
                        "service_id": 20480, "instance_id": 1, "major_version": 1, "minor_version": 0,
                        "find_on": ["primary"]
                    }
                }
            )
            gen2.save(os.path.join(output_dir, "config_client.json"))
            
            logger.info(f"Generated split large_payload configs (single host) in {output_dir}")
            return output_dir

