import os
import sys
import subprocess
import threading
import queue
import datetime
import time
import re
import logging

logger = logging.getLogger("fusion.execution")

class AppRunner:
    """
    Standardized runner for Fusion application instances (Python, C++, Rust, JS).
    Handles process lifecycle, logging (tee), and synchronization.
    Supports network namespaces on Linux and sudo execution.
    """
    def __init__(self, name, cmd, log_dir, cwd=None, env=None, ns=None, use_sudo=False):
        self.name = name
        self.cmd = cmd
        self.log_dir = log_dir
        self.cwd = cwd or os.getcwd()
        self.env = os.environ.copy()
        if env:
            self.env.update(env)
        self.ns = ns
        self.use_sudo = use_sudo
        
        self.is_ci = bool(os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS'))
        self.proc = None
        self.log_file = None
        self.all_output = []
        self.output_pos = 0
        self.output_lock = threading.Lock()
        self._stop_event = threading.Event()
        self.reader_thread = None
        
        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, f"{self.name}.log")

    def _prepare_cmd(self):
        final_cmd = self.cmd.copy()
        
        # Handle sudo and namespaces
        if sys.platform == "linux":
            prefix = []
            
            # Root prefix
            if self.use_sudo:
                prefix = ["sudo"]
                if self.is_ci:
                    prefix.append("-n")
            elif self.ns and os.geteuid() != 0:
                # netns always needs sudo
                prefix = ["sudo"]
                if self.is_ci:
                    prefix.append("-n")
            
            if self.ns:
                prefix.extend(["ip", "netns", "exec", self.ns])
            
            # Environment wrapper
            # sudo -E is sometimes blocked, so we explicitly set key variables via 'env'
            env_cmd = ["env"]
            if "PYTHONPATH" in self.env:
                env_cmd.append(f"PYTHONPATH={self.env['PYTHONPATH']}")
            
            # Always pass HOME so users can find .npm etc
            home = self.env.get('HOME') or os.environ.get('HOME')
            if home:
                env_cmd.append(f"HOME={home}")
            
            final_cmd = prefix + env_cmd + final_cmd
            
        return final_cmd

    def start(self):
        """Starts the application process."""
        self.log_file = open(self.log_path, "w", encoding='utf-8', errors='ignore')
        self.log_file.write(f"=== FUSION APP RUNNER: {self.name} ===\n")
        self.log_file.write(f"START_TIME: {datetime.datetime.now()}\n")
        self.log_file.write(f"COMMAND: {' '.join(self.cmd)}\n")
        self.log_file.write(f"CWD: {self.cwd}\n")
        if self.ns: self.log_file.write(f"NS: {self.ns}\n")
        self.log_file.write("="*40 + "\n\n")
        self.log_file.flush()

        final_cmd = self._prepare_cmd()
        
        try:
            self.proc = subprocess.Popen(
                final_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cwd,
                env=self.env,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
        except Exception as e:
            msg = f"Failed to start process {self.name}: {e}"
            self.log_file.write(f"\n[ERROR] {msg}\n")
            self.log_file.close()
            raise RuntimeError(msg)

        self.reader_thread = threading.Thread(target=self._reader_loop, name=f"Reader-{self.name}")
        self.reader_thread.daemon = True
        self.reader_thread.start()
        
        logger.info(f"Started {self.name} (PID: {self.proc.pid})")

    def _reader_loop(self):
        """Internal loop to read output and tee to log file and queue."""
        try:
            for line in iter(self.proc.stdout.readline, ''):
                if self._stop_event.is_set():
                    break
                
                # Write to log
                self.log_file.write(line)
                self.log_file.flush()
                
                # Save to buffer for non-destructive wait_for_output
                with self.output_lock:
                    self.all_output.append(line)
            
            # Ensure we consume remaining output if process exited
            if self.proc:
                self.proc.stdout.close()
        except Exception as e:
            if not self._stop_event.is_set():
                 logger.error(f"Reader loop error for {self.name}: {e}")
        finally:
            if self.log_file:
                self.log_file.write(f"\n--- Process Exited with code {self.proc.poll()} ---\n")
                self.log_file.flush()

    def wait_for_output(self, pattern, timeout=30, description=None):
        """
        Waits for a specific regex pattern in the output (non-destructive).
        Returns the matching line or None if timeout.
        """
        start_time = time.time()
        regex = re.compile(pattern)
        desc = f" ({description})" if description else ""
        
        while time.time() - start_time < timeout:
            # Check existing output in buffer
            with self.output_lock:
                local_pos = self.output_pos
                while local_pos < len(self.all_output):
                    line = self.all_output[local_pos]
                    local_pos += 1
                    if regex.search(line):
                        self.output_pos = local_pos
                        return line
            
            # If line not found yet, check if process is still running
            if self.proc.poll() is not None:
                # Process exited, do one final check of the remaining buffer
                with self.output_lock:
                    local_pos = self.output_pos
                    while local_pos < len(self.all_output):
                        line = self.all_output[local_pos]
                        local_pos += 1
                        if regex.search(line):
                            self.output_pos = local_pos
                            return line
                
                logger.warning(f"Process {self.name} exited with code {self.proc.returncode} while waiting for '{pattern}'{desc}")
                break
                
            # Wait for more output to arrive
            time.sleep(0.1)
        
        # Diagnostics for timeout
        err_msg = f"Timed out waiting for '{pattern}' in {self.name}{desc}"
        logger.error(err_msg)
        if self.proc.poll() is not None:
             logger.error(f"  [PROCESS STATUS] {self.name} has already exited with code {self.proc.returncode}")

        return None
    
    def clear_output(self):
        """Advances the internal cursor to the end of current output (effectively clearing it for next waiter)."""
        with self.output_lock:
            self.output_pos = len(self.all_output)

    def stop(self, timeout=5):
        """Stops the application process."""
        if not self.proc:
            return

        self._stop_event.set()
        
        logger.info(f"Stopping {self.name}...")
        
        # Try graceful termination
        try:
            if os.name == 'nt' and self.proc.poll() is None:
                # On Windows, taskkill /T /F is a reliable way to kill a process tree
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.proc.terminate()
            
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(f"{self.name} did not terminate gracefully, killing...")
                self.proc.kill()
                self.proc.wait()
        except Exception as e:
            logger.error(f"Error stopping {self.name}: {e}")

        if self.reader_thread:
            self.reader_thread.join(timeout=1)
            
        if self.log_file:
            self.log_file.close()
            self.log_file = None
            
        self.proc = None

    def get_output(self):
        """Returns the current log output as a string."""
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r", encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except Exception as e:
                return f"[Error reading log {self.log_path}: {e}]"
        return ""

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def get_return_code(self):
        if self.proc:
            return self.proc.poll()
        return None
