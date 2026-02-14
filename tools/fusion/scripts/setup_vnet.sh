#!/bin/bash
# setup_vnet.sh — Setup Virtual Network with Multicast & Checksum Fixes
# Usage: sudo bash setup_vnet.sh

set -euo pipefail

SUBNET=10.0.1
SUBNET2=10.0.2
ECUS=("ns_ecu1" "ns_ecu2" "ns_ecu3")

# Check for ethtool (Crucial for fixing UDP checksums)
if ! command -v ethtool &> /dev/null; then
    echo "ERROR: 'ethtool' is not installed. Please run: sudo apt install ethtool"
    exit 1
fi

echo "=== Setting up SOME/IP Virtual Network (Namespaces) ==="

# --- 0. Host Cleanup & Firewall Prep ---
# WSL/Ubuntu often blocks bridge traffic by default. We must allow it.
echo "[0/4] Preparing Host Firewall & Sysctl..."
iptables -P FORWARD ACCEPT || true
iptables -F FORWARD || true
# Ensure ARP and Multicast aren't blocked by ebtables/nftables
sysctl -w net.bridge.bridge-nf-call-iptables=0 > /dev/null 2>&1 || true
sysctl -w net.bridge.bridge-nf-call-ip6tables=0 > /dev/null 2>&1 || true
sysctl -w net.bridge.bridge-nf-call-arptables=0 > /dev/null 2>&1 || true

# Pre-emptively disable RP Filter globally
sysctl -w net.ipv4.conf.all.rp_filter=0 > /dev/null 2>&1 || true
sysctl -w net.ipv4.conf.default.rp_filter=0 > /dev/null 2>&1 || true

# 1. Create bridges
for i in 0 1; do
    BR="br$i"
    NET="10.0.$((i+1))"
    echo "[1/4] Creating bridge $BR ($NET.254)..."
    # Delete if exists to start fresh
    ip link delete $BR type bridge 2>/dev/null || true
    
    ip link add name $BR type bridge
    ip link set $BR up
    ip addr add ${NET}.254/24 dev $BR
    # Disable snooping so bridge acts like a dumb hub (floods multicast)
    ip link set dev $BR type bridge mcast_snooping 0
    ip link set $BR promisc on
    
    # Disable Checksums and RP Filter on Bridge
    ethtool -K $BR rx off tx off sg off >/dev/null 2>&1 || true
    sysctl -w net.ipv4.conf.$BR.rp_filter=0 > /dev/null 2>&1 || true
done

# 2. Create namespaces and veth pairs
echo "[2/4] Creating namespaces and veth pairs..."
for i in "${!ECUS[@]}"; do
    NS=${ECUS[$i]}
    IDX=$((i + 1))
    
    # Clean up old namespace if exists
    ip netns del "$NS" 2>/dev/null || true
    
    # Create namespace
    ip netns add "$NS"
    ip netns exec "$NS" ip link set lo up

    # Function to create an interface
    create_iface() {
        local ns=$1
        local v_host=$2
        local v_ns=$3
        local br=$4
        local ip_addr=$5
        local mac_suf=$6
        local route_metric=$7

        # Create pair
        ip link add "$v_host" type veth peer name "$v_ns"
        
        # --- HOST SIDE CONFIG ---
        ip link set "$v_host" master $br
        ip link set "$v_host" up
        ip link set "$v_host" promisc on
        ip link set dev "$v_host" multicast on
        # CRITICAL FIX: Disable checksum offload on HOST side interface
        ethtool -K "$v_host" rx off tx off sg off >/dev/null 2>&1 || true
        # Disable RP Filter on Host Side Veth
        sysctl -w net.ipv4.conf.$v_host.rp_filter=0 > /dev/null 2>&1 || true
        
        # --- NAMESPACE SIDE CONFIG ---
        ip link set "$v_ns" netns "$ns"
        
        ip netns exec "$ns" ip link set dev "$v_ns" address "02:00:00:00:00:0$mac_suf"
        ip netns exec "$ns" ip addr add "$ip_addr" dev "$v_ns"
        ip netns exec "$ns" ip link set "$v_ns" up
        ip netns exec "$ns" ip link set dev "$v_ns" multicast on
        
        # CRITICAL FIX: Disable checksum offload on NAMESPACE side interface
        ip netns exec "$ns" ethtool -K "$v_ns" rx off tx off sg off >/dev/null 2>&1 || true

        # Add Multicast Route with Metric
        ip netns exec "$ns" ip route add 224.0.0.0/4 dev "$v_ns" metric "$route_metric" || true
    }

    # Setup Primary Interface (veth0 -> br0)
    create_iface "$NS" "veth_${NS}_h0" "veth0" "br0" "${SUBNET}.${IDX}/24" "$IDX" 10
    
    # Default gateway - retry logic just in case
    # Ensuring veth0 is up and ready
    ip netns exec "$NS" ip link set veth0 up
    if ! ip netns exec "$NS" ip route add default via ${SUBNET}.254; then
        echo "WARNING: Failed to add default route for $NS via ${SUBNET}.254. Retrying..."
        sleep 1
        ip netns exec "$NS" ip route add default via ${SUBNET}.254 || echo "ERROR: Could not add default route"
    fi

    # Specific for ns_ecu1: Secondary Interface (veth1 -> br1)
    if [ "$NS" == "ns_ecu1" ]; then
        create_iface "$NS" "veth_${NS}_h1" "veth1" "br1" "${SUBNET2}.${IDX}/24" "$IDX" 20
    fi
    
    # Permissive Security Settings
    ip netns exec "$NS" sysctl -w net.ipv4.conf.all.rp_filter=0 > /dev/null
    ip netns exec "$NS" sysctl -w net.ipv4.conf.default.rp_filter=0 > /dev/null
    ip netns exec "$NS" sysctl -w net.ipv4.conf.veth0.rp_filter=0 > /dev/null
    ip netns exec "$NS" ip neighbor flush all || true
done

# 3. Tuning host network
echo "[3/4] Tuning host network..."
sysctl -w net.ipv4.ip_forward=1 > /dev/null

# 4. Verify Pings
echo "[4/4] Verifying connectivity (ICMP)..."
for i in "${!ECUS[@]}"; do
    NS=${ECUS[$i]}
    IDX=$((i + 1))
    echo -n "  $NS (${SUBNET}.${IDX}): "
    if ip netns exec "$NS" ping -c 1 -W 1 ${SUBNET}.254 > /dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
    fi
done

echo ""
echo "=== Virtual Network Ready ==="
echo "Namespaces: ${ECUS[*]}"
echo ""