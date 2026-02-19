#!/bin/bash
# setup_vnet.sh — Setup Virtual Network with Dual-Stack (IPv4 + IPv6), Multicast & Checksum Fixes
# Usage: sudo bash setup_vnet.sh
#
# Topology:
#   br0 (10.0.1.0/24, fd00:1::/64) — primary bridge
#   br1 (10.0.2.0/24, fd00:2::/64) — secondary bridge (ns_ecu1 dual-homed)
#
#   ns_ecu1: veth0@br0 (10.0.1.1, fd00:1::1) + veth1@br1 (10.0.2.1, fd00:2::1)
#   ns_ecu2: veth0@br0 (10.0.1.2, fd00:1::2)
#   ns_ecu3: veth0@br0 (10.0.1.3, fd00:1::3)
#
# IPv6 addresses use ULA (Unique Local Address) range fd00::/8.
# This is routable within the VNet (unlike link-local fe80::) and appropriate
# for private automotive networks. Compatible with future migration to GUA if needed.

set -euo pipefail

SUBNET=10.0.1
SUBNET2=10.0.2
SUBNET6="fd00:1"
SUBNET6_2="fd00:2"
ECUS=("ns_ecu1" "ns_ecu2" "ns_ecu3")

# Check for ethtool (Crucial for fixing UDP checksums)
if ! command -v ethtool &> /dev/null; then
    echo "ERROR: 'ethtool' is not installed. Please run: sudo apt install ethtool"
    exit 1
fi

echo "=== Setting up SOME/IP Virtual Network (Dual-Stack: IPv4 + IPv6) ==="

# --- 0. Host Cleanup & Firewall Prep ---
# WSL/Ubuntu often blocks bridge traffic by default. We must allow it.
echo "[0/5] Preparing Host Firewall & Sysctl..."
iptables -P FORWARD ACCEPT || true
iptables -F FORWARD || true
# Ensure ARP and Multicast aren't blocked by ebtables/nftables
sysctl -w net.bridge.bridge-nf-call-iptables=0 > /dev/null 2>&1 || true
sysctl -w net.bridge.bridge-nf-call-ip6tables=0 > /dev/null 2>&1 || true
sysctl -w net.bridge.bridge-nf-call-arptables=0 > /dev/null 2>&1 || true

# Pre-emptively disable RP Filter globally
sysctl -w net.ipv4.conf.all.rp_filter=0 > /dev/null 2>&1 || true
sysctl -w net.ipv4.conf.default.rp_filter=0 > /dev/null 2>&1 || true

# Enable IPv6 forwarding globally
sysctl -w net.ipv6.conf.all.forwarding=1 > /dev/null 2>&1 || true
sysctl -w net.ipv6.conf.default.forwarding=1 > /dev/null 2>&1 || true

# 1. Create bridges
for i in 0 1; do
    BR="br$i"
    NET="10.0.$((i+1))"
    NET6="fd00:$((i+1))"
    echo "[1/5] Creating bridge $BR ($NET.254, ${NET6}::254)..."
    # Delete if exists to start fresh
    ip link delete $BR type bridge 2>/dev/null || true
    
    ip link add name $BR type bridge
    ip link set $BR up
    # IPv4 address
    ip addr add ${NET}.254/24 dev $BR
    # IPv6 ULA address
    ip addr add ${NET6}::254/64 dev $BR
    # Disable snooping so bridge acts like a dumb hub (floods multicast)
    ip link set dev $BR type bridge mcast_snooping 0
    ip link set $BR promisc on
    
    # Disable Checksums and RP Filter on Bridge
    ethtool -K $BR rx off tx off sg off >/dev/null 2>&1 || true
    sysctl -w net.ipv4.conf.$BR.rp_filter=0 > /dev/null 2>&1 || true
    # Disable IPv6 DAD on bridge (avoids delays)
    sysctl -w net.ipv6.conf.$BR.accept_dad=0 > /dev/null 2>&1 || true
done

# 2. Create namespaces and veth pairs
echo "[2/5] Creating namespaces and veth pairs..."
for i in "${!ECUS[@]}"; do
    NS=${ECUS[$i]}
    IDX=$((i + 1))
    
    # Clean up old namespace if exists
    ip netns del "$NS" 2>/dev/null || true
    
    # Create namespace
    ip netns add "$NS"
    ip netns exec "$NS" ip link set lo up

    # Enable IPv6 inside namespace
    ip netns exec "$NS" sysctl -w net.ipv6.conf.all.disable_ipv6=0 > /dev/null 2>&1 || true
    ip netns exec "$NS" sysctl -w net.ipv6.conf.default.disable_ipv6=0 > /dev/null 2>&1 || true

    # Function to create an interface
    create_iface() {
        local ns=$1
        local v_host=$2
        local v_ns=$3
        local br=$4
        local ip_addr=$5
        local ip6_addr=$6
        local mac_suf=$7
        local route_metric=$8

        # Create pair
        ip link delete "$v_host" 2>/dev/null || true
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
        # IPv4 address
        ip netns exec "$ns" ip addr add "$ip_addr" dev "$v_ns"
        # IPv6 ULA address
        ip netns exec "$ns" ip addr add "$ip6_addr" dev "$v_ns"
        ip netns exec "$ns" ip link set "$v_ns" up
        ip netns exec "$ns" ip link set dev "$v_ns" multicast on
        
        # CRITICAL FIX: Disable checksum offload on NAMESPACE side interface
        ip netns exec "$ns" ethtool -K "$v_ns" rx off tx off sg off >/dev/null 2>&1 || true

        # Disable DAD to avoid address assignment delays
        ip netns exec "$ns" sysctl -w net.ipv6.conf.$v_ns.accept_dad=0 > /dev/null 2>&1 || true

        # Add IPv4 Multicast Route with Metric
        ip netns exec "$ns" ip route add 224.0.0.0/4 dev "$v_ns" metric "$route_metric" || true
        # Add IPv6 Multicast Route
        ip netns exec "$ns" ip -6 route add ff00::/8 dev "$v_ns" metric "$route_metric" || true
    }

    # Setup Primary Interface (veth0 -> br0)
    create_iface "$NS" "veth_${NS}_h0" "veth0" "br0" \
        "${SUBNET}.${IDX}/24" "${SUBNET6}::${IDX}/64" \
        "$IDX" 10
    
    # Default gateway (IPv4) - retry logic just in case
    # Ensuring veth0 is up and ready
    ip netns exec "$NS" ip link set veth0 up
    if ! ip netns exec "$NS" ip route add default via ${SUBNET}.254; then
        echo "WARNING: Failed to add default route for $NS via ${SUBNET}.254. Retrying..."
        sleep 1
        ip netns exec "$NS" ip route add default via ${SUBNET}.254 || echo "ERROR: Could not add default route"
    fi
    # Default gateway (IPv6)
    ip netns exec "$NS" ip -6 route add default via ${SUBNET6}::254 || true

    # Specific for ns_ecu1: Secondary Interface (veth1 -> br1)
    if [ "$NS" == "ns_ecu1" ]; then
        create_iface "$NS" "veth_${NS}_h1" "veth1" "br1" \
            "${SUBNET2}.${IDX}/24" "${SUBNET6_2}::${IDX}/64" \
            "$IDX" 20
    fi
    
    # Permissive Security Settings
    ip netns exec "$NS" sysctl -w net.ipv4.conf.all.rp_filter=0 > /dev/null
    ip netns exec "$NS" sysctl -w net.ipv4.conf.default.rp_filter=0 > /dev/null
    ip netns exec "$NS" sysctl -w net.ipv4.conf.veth0.rp_filter=0 > /dev/null
    ip netns exec "$NS" ip neighbor flush all || true
done

# 3. Tuning host network
echo "[3/5] Tuning host network..."
sysctl -w net.ipv4.ip_forward=1 > /dev/null
sysctl -w net.ipv6.conf.all.forwarding=1 > /dev/null

# 4. Verify IPv4 Connectivity (ICMP)
echo "[4/5] Verifying IPv4 connectivity (ICMP)..."
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

# 5. Verify IPv6 Connectivity (ICMPv6)
echo "[5/5] Verifying IPv6 connectivity (ICMPv6)..."
for i in "${!ECUS[@]}"; do
    NS=${ECUS[$i]}
    IDX=$((i + 1))
    echo -n "  $NS (${SUBNET6}::${IDX}): "
    
    # Retry loop because IPv6 DAD (Duplicate Address Detection) might take a moment
    SUCCESS=0
    for retry in {1..5}; do
        if ip netns exec "$NS" ping -6 -c 1 -W 1 ${SUBNET6}::254 > /dev/null 2>&1; then
            echo "OK"
            SUCCESS=1
            break
        fi
        sleep 1
    done
    if [ $SUCCESS -eq 0 ]; then
        echo "FAIL (IPv6 failed to settle after 5 seconds)"
    fi
done

echo ""
echo "=== Virtual Network Ready (Dual-Stack: IPv4 + IPv6) ==="
echo "Namespaces: ${ECUS[*]}"
echo "Bridge br0: ${SUBNET}.254 / ${SUBNET6}::254"
echo "Bridge br1: ${SUBNET2}.254 / ${SUBNET6_2}::254"
echo ""