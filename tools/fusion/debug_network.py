import socket
import os
import subprocess
import platform
import ipaddress

def debug_network():
    print(f"Platform: {platform.system()}")
    print(f"Network Interfaces (python): {socket.if_nameindex()}")
    
    # 1. Detect IPv4
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip4 = s.getsockname()[0]
        s.close()
        print(f"Detected IPv4 via socket: {ip4}")
    except Exception as e:
        print(f"IPv4 detection failed: {e}")

    # 2. Detect IPv6
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        # Link-local multicast or similar to find interface
        s.connect(('ff02::1', 1)) 
        ip6 = s.getsockname()[0]
        s.close()
        print(f"Detected IPv6 via socket: {ip6}")
    except Exception as e:
        print(f"IPv6 detection failed: {e}")

    # 3. 'ip route' check (Linux/WSL)
    if platform.system() == "Linux" or True: # Run it anyway to check if we can
        try:
            print("\n--- ip route get 10.255.255.255 ---")
            cmd = ["ip", "route", "get", "10.255.255.255"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(f"Return code: {result.returncode}")
            print(f"Stdout: {result.stdout.strip()}")
            print(f"Stderr: {result.stderr.strip()}")
            
            if result.returncode == 0:
                parts = result.stdout.split()
                if "dev" in parts:
                    idx = parts.index("dev")
                    if idx + 1 < len(parts):
                        print(f"Parsed Interface: {parts[idx+1]}")
                    else:
                        print("Found 'dev' but no interface name after it.")
                else:
                    print("'dev' not found in output.")
        except FileNotFoundError:
            print("'ip' command not found.")
        except Exception as e:
            print(f"Error running ip route: {e}")

    # 4. 'ip addr' check
    if platform.system() == "Linux" or True:
        try:
            print("\n--- ip addr ---")
            cmd = ["ip", "addr"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result.stdout)
        except Exception:
            pass

if __name__ == "__main__":
    debug_network()
