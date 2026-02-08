
import os
import json
import shutil
import sys
sys.path.append(os.getcwd())
import tools.fusion.utils as utils

# Setup
config_path = "tests/tcp_test_config.json"
backup_path = config_path + ".bak"
if os.path.exists(config_path):
    import shutil
    shutil.copy2(config_path, backup_path)

# Run Patch
print(f"Original IP in {config_path}:")
with open(config_path, 'r') as f:
    data = json.load(f)
    print(data['endpoints']['server_tcp']['ip'])

print("\nPatching...")
# We assume we can detect a local IP. If not, we use fake one.
# But cleaner to use the real one to match fusion behavior.
detected_ip = utils.get_local_ip()
print(f"Detected IP: {detected_ip}")
utils.patch_configs(detected_ip, os.getcwd())

print(f"\nNew IP in {config_path}:")
with open(config_path, 'r') as f:
    data = json.load(f)
    print(data['endpoints']['server_tcp']['ip'])
    
# Clean up backup
if os.path.exists(backup_path):
    os.remove(backup_path) # We don't restore, we verify it *was* patched. Wait, if I run fusion later it patches anyway.
