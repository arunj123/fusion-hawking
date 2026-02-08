import sys
import os
# Add root to path
sys.path.append(os.getcwd())
from tools.fusion import utils

print("--- Testing utils.get_network_info() ---")
info = utils.get_network_info()
print(f"Info: {info}")

if info['ipv4']:
    print(f"SUCCESS: Detected IPv4: {info['ipv4']}")
else:
    print("FAILURE: No IPv4 detected")

if info['interface']:
    print(f"SUCCESS: Detected Interface: {info['interface']}")
else:
    print("WARNING: No Interface detected (might be expected on some envs but checked WSL logic)")

print(f"IPv6: {info['ipv6']}")
