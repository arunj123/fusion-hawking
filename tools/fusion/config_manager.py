import json
import os
import copy
import ipaddress
from .environment import NetworkEnvironment

class ConfigGenerator:
    def __init__(self, environment: NetworkEnvironment):
        self.env = environment

    def generate(self, template_path, output_path, topology="host", port_offset=0, override_ipv4=None):
        """
        Generates a configuration file from a template based on the topology.
        topology: "host" | "vnet" | "loopback"
        """
        with open(template_path, 'r') as f:
            config = json.load(f)

        if topology == "vnet" and not self.env.has_vnet:
             # Fallback or Error?
             # For now error to be explicit
             raise RuntimeError("VNet topology requested but VNet not detected.")
        
        # If override_ipv4 provided, use it to decide topology if generic "host"
        # But caller usually decides topology.
        
        self._map_interfaces(config, topology, override_ipv4)
        self._map_instances(config, topology)
        self._apply_port_offset(config, port_offset)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(config, f, indent=4)
        # print(f"Generated config {output_path} for topology {topology} (Override: {override_ipv4})")

    def _map_interfaces(self, config, topology, override_ipv4):
        if "interfaces" not in config: return
        
        for iface_name, iface_cfg in config["interfaces"].items():
            # Determine target interface name
            target_name = iface_cfg.get("name")
            
            if topology == "loopback":
                target_name = "lo" if self.env.os_type != "Windows" else "Loopback Pseudo-Interface 1"
            elif topology == "host":
                # Use primary interface for everything unless it's explicitly loopback
                if target_name != "lo":
                    target_name = self.env.primary_interface or "eth0"
            elif topology == "vnet":
                if target_name == "eth0": target_name = "veth0"
            
            if target_name:
                iface_cfg["name"] = target_name

            # Map Endpoints
            self._map_endpoints(iface_cfg.get("endpoints", {}), topology, iface_name, override_ipv4)

    def _map_endpoints(self, endpoints, topology, iface_name, override_ipv4):
        for ep_name, ep in endpoints.items():
            if "ip" not in ep: continue
            original_ip = ep["ip"]
            new_ip = original_ip
            
            try:
                # IPv6 Scope Patching for Linux
                if self.env.os_type == 'Linux' and original_ip.lower().startswith('ff02:'):
                     new_ip = "ff0e:" + original_ip[5:]
                
                obj = ipaddress.ip_address(original_ip)
                
                if obj.is_multicast:
                    pass # Don't override multicast IPs with unicast override_ipv4
                elif obj.is_loopback:
                     if topology == "host" and self.env.primary_ip:
                         pass
                elif topology == "loopback":
                    new_ip = "127.0.0.1"
                elif override_ipv4:
                    # Apply override if not multicast and not explicitly ignored?
                    # Legacy patch_configs applied it if valid IP.
                    new_ip = override_ipv4
                
            except: pass
            
            ep["ip"] = new_ip
            
            # Map Interface in Endpoint (if exists)
            # REMOVED: Legacy behavior incorrectly added 'interface' to endpoints.
            # The interface association is handled by hierarchy (endpoints are inside an interface).
            if "interface" in ep:
                del ep["interface"]


    def _map_instances(self, config, topology):
        # Unicast Bind Injection for Windows Loopback
        if self.env.os_type == 'Windows' and topology == "loopback":
            if "instances" in config:
                for inst_name, inst_cfg in config["instances"].items():
                    unicast_bind = inst_cfg.get("unicast_bind", {})
                    # Inject for all loopback interfaces
                    if "interfaces" in config:
                        for iface_key, iface_cfg in config["interfaces"].items():
                             # If interface is mapped to loopback (which it should be in loopback topology)
                             # We inject the bind
                             if iface_key not in unicast_bind:
                                 # Try to find a unicast endpoint to bind to
                                 # Usually "_sd_bind_v4"
                                 if "_sd_bind_v4" in iface_cfg.get("endpoints", {}):
                                     unicast_bind[iface_key] = "_sd_bind_v4"
                    inst_cfg["unicast_bind"] = unicast_bind

    def _apply_port_offset(self, config, offset):
        if offset == 0: return
        
        # Patch interfaces->endpoints->port
        if "interfaces" in config:
            for iface in config["interfaces"].values():
                for ep in iface.get("endpoints", {}).values():
                    if "port" in ep and isinstance(ep["port"], int):
                        ep["port"] += offset
                        
        # Patch service_discovery->multicast_port
        if "service_discovery" in config:
            sd = config["service_discovery"]
            if "multicast_port" in sd and isinstance(sd["multicast_port"], int):
                sd["multicast_port"] += offset

