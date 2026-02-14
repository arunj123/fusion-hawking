import subprocess
import time
import sys
import os

def run():
    env = os.environ.copy()
    env["PYTHONPATH"] = "../../src/python"
    env["PYTHONUNBUFFERED"] = "1"
    env["FUSION_PACKET_DUMP"] = "1"
    
    with open("daemon.log", "w") as d_f, \
         open("service.log", "w") as s_f, \
         open("client.log", "w") as c_f:
         
        # Start daemon
        print("--- Starting Daemon ---")
        daemon = subprocess.Popen([sys.executable, "start_daemon.py"],
                                   stdout=d_f, stderr=subprocess.STDOUT, text=True, env=env)
        time.sleep(3)

        # Start service
        print("--- Starting Service ---")
        service = subprocess.Popen([sys.executable, "service_someipy.py"], 
                                   stdout=s_f, stderr=subprocess.STDOUT, text=True, env=env)
        
        # Wait for service to offer
        time.sleep(5)
        
        # Start client
        print("--- Starting Client ---")
        client = subprocess.Popen([sys.executable, "client_fusion.py"], 
                                  stdout=c_f, stderr=subprocess.STDOUT, text=True, env=env)
        
        # Wait for client to finish
        timeout = 15
        start_time = time.time()
        while client.poll() is None and (time.time() - start_time) < timeout:
            time.sleep(1)
            
        if client.poll() is None:
            print("--- Client Timed Out ---")
            client.terminate()
        else:
            print(f"--- Client Finished with code {client.returncode} ---")
            
        service.terminate()
        daemon.terminate()

    print("--- Debug Finished ---")

if __name__ == "__main__":
    run()
