import argparse
import json
import sys
import os
from .config_validator import validate_config

def load_config(path):
    with open(path, "r") as f:
        return json.load(f)

def save_config(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
        
def cmd_validate(args):
    try:
        data = load_config(args.config_file)
        errors = validate_config(data)
        if errors:
            print("Validation Failed:")
            for e in errors:
                print(f" - {e}")
            sys.exit(1)
        else:
            print("Configuration is valid.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def cmd_add_service(args):
    try:
        data = load_config(args.config_file)
        instances = data.get("instances", {})
        
        if args.instance not in instances:
            print(f"Error: Instance '{args.instance}' not found.")
            sys.exit(1)
            
        inst = instances[args.instance]
        if "providing" not in inst:
            inst["providing"] = {}
            
        svc = {
            "service_id": args.id,
            "instance_id": args.instance_id,
            "major_version": args.major,
            "minor_version": args.minor,
            "port": args.port,
            "protocol": "udp"
        }
        
        if args.mc_ip or args.mc_port:
            svc["multicast"] = {
                "ip": args.mc_ip,
                "port": args.mc_port
            }
            
        inst["providing"][args.service] = svc
        
        # Validate before saving
        errors = validate_config(data)
        if errors:
            print("Proposed change invalid:")
            for e in errors:
                print(f" - {e}")
            sys.exit(1)
            
        save_config(args.config_file, data)
        print(f"Service '{args.service}' added to '{args.instance}'.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Fusion Configuration Helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Validate
    v_parser = subparsers.add_parser("validate", help="Validate a config file")
    v_parser.add_argument("config_file", help="Path to config.json")
    
    # Add Service
    a_parser = subparsers.add_parser("add-service", help="Add a service to an instance")
    a_parser.add_argument("config_file", help="Path to config.json")
    a_parser.add_argument("--instance", required=True, help="Instance name")
    a_parser.add_argument("--service", required=True, help="Service name")
    a_parser.add_argument("--id", required=True, type=int, help="Service ID")
    a_parser.add_argument("--instance-id", type=int, default=1, help="Instance ID")
    a_parser.add_argument("--major", type=int, default=1, help="Major version")
    a_parser.add_argument("--minor", type=int, default=0, help="Minor version")
    a_parser.add_argument("--port", type=int, required=True, help="Unicast port")
    a_parser.add_argument("--mc-ip", help="Multicast IP")
    a_parser.add_argument("--mc-port", type=int, help="Multicast Port")
    
    args = parser.parse_args()
    
    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "add-service":
        cmd_add_service(args)

if __name__ == "__main__":
    main()
