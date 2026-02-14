import subprocess
import sys
import time

def run_ping(src_ns, dest_ip):
    print(f"Pinging {dest_ip} from {src_ns}...")
    try:
        cmd = ["sudo", "ip", "netns", "exec", src_ns, "ping", "-c", "3", "-W", "1", dest_ip]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"SUCCESS: {src_ns} -> {dest_ip}")
            return True
        else:
            print(f"FAIL: {src_ns} -> {dest_ip}")
            print(result.stderr)
            print(result.stdout)
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def main():
    # Verify setup_vnet.sh result
    # ns_ecu1: 10.0.1.1
    # ns_ecu2: 10.0.1.2
    # ns_ecu3: 10.0.1.3
    
    success = True
    
    # Check 1 -> 2
    if not run_ping("ns_ecu1", "10.0.1.2"): success = False
    
    # Check 1 -> 3 (Verified by test_a implicitly)
    if not run_ping("ns_ecu1", "10.0.1.3"): success = False
    
    # Check 2 -> 3
    if not run_ping("ns_ecu2", "10.0.1.3"): success = False
    
    # Check 3 -> 1
    if not run_ping("ns_ecu3", "10.0.1.1"): success = False
    
    # Check 3 -> 2
    if not run_ping("ns_ecu3", "10.0.1.2"): success = False

    if success:
        print("\nALL CONNECTIVITY CHECKS PASSED")
        sys.exit(0)
    else:
        print("\nSOME CHECKS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
