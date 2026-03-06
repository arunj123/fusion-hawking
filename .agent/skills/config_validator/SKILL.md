---
name: Config Validator
description: Statically validate the syntactic and semantic correctness of config.json configurations to catch port or ID conflicts.
---
# Config Validator Skill

## Usage
Use this skill whenever you modify or create a `config.json` file for the Fusion Hawking project. This script will ensure:
- The config strictly matches the expected JSON schema.
- There are no unmapped interfaces or endpoints.
- There are no Port conflicts between services.
- There are no duplicate `(Service ID, Instance ID, Major Version)` combinations provided on the network.

## Command
To run the configuration validator, execute the following script from the project root:

```bash
python tools/fusion/config_validator.py path/to/your/config.json
```

## Output
If the configuration is valid:
```
Configuration 'path/to/your/config.json' is valid.
```
If errors are found, the script exits with `1` and prints descriptive errors, e.g.:
```
Configuration Errors Found:
 - Duplicate Service (ID: 100, Instance: 1, Major: 1) provided by: InstanceA:Svc1, InstanceB:Svc2
 - Port Conflict on eth0/192.168.1.10:30501/udp: Used by InstanceA:Svc1, InstanceA:Svc3
```
