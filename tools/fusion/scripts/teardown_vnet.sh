#!/bin/bash
# teardown_vnet.sh — Remove the virtual network topology created by setup_vnet.sh
# Usage: sudo bash teardown_vnet.sh

set -euo pipefail

BRIDGE=br0

echo "=== Tearing down SOME/IP Virtual Network (Namespaces) ==="

# 1. Aggressively remove all veth interfaces
echo "  Purging all veth interfaces..."
for link in $(ip link show | grep -oE 'veth[a-zA-Z0-9_-]*(@if[0-9]+)?' | cut -d'@' -f1 | sort -u); do
    echo "    Removing $link"
    ip link del "$link" 2>/dev/null || true
done

# 2. Remove bridges
for BRIDGE in br0 br1; do
    if ip link show $BRIDGE > /dev/null 2>&1; then
        echo "  Removing bridge: $BRIDGE"
        ip link set $BRIDGE down
        ip link del $BRIDGE || true
    fi
done

# 3. Remove all namespaces
echo "  Purging all network namespaces..."
for NS in $(ip netns list | cut -d' ' -f1); do
    echo "    Removing $NS"
    ip netns del "$NS" 2>/dev/null || true
done

echo "=== Virtual Network Removed ==="
