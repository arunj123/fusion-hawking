---
name: ID Manager
description: Scan the codebase for allocated Service IDs to find duplicates or suggest the next available ID.
---
# ID Manager Skill

## Usage
Use this skill when you need to mint a new Service ID or verify that an existing Service ID is completely unique across the Python codebase. It prevents conflicts in service discovery.

## Command
To run the ID Manager, execute the following script from the project root:

```bash
python tools/id_manager/manager.py
```

## Output
The script will output all currently used IDs and their corresponding files, followed by the next available ID.

Example Output:
```
Used IDs:
  0x1234: src/service_a.py (SERVICE_ID)
  0x1111: examples/demo.py (SERVICE_ID)

Next Available ID: 0x1235
```
