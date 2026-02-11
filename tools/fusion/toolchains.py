import shutil
import subprocess
import sys
import os

class ToolchainManager:
    """Manages detection and setup of required tools."""
    
    def __init__(self):
        self.status = {
            "rust": False,
            "cargo": False,
            "cmake": False,
            "python": True, # Running in it
            "pip": True,
            "opencppcoverage": False,
            "rust_cov": False,
            "lcov": False,
            "genhtml": False
        }

    def check_all(self):
        """Checks for all required tools."""
        print("Checking toolchain...")
        self.status["rust"] = self._check_command("rustc", "--version")
        self.status["cargo"] = self._check_command("cargo", "--version")
        self.status["cmake"] = self._check_command("cmake", "--version")
        self.status["opencppcoverage"] = self._check_command("OpenCppCoverage", "--help")
        
        # Check pip
        try:
            subprocess.run([sys.executable, "-m", "pip", "--version"], check=True, capture_output=True)
            self.status["pip"] = True
        except:
            self.status["pip"] = False
            
        # Check cargo-llvm-cov
        self.status["rust_cov"] = self._check_command("cargo-llvm-cov", "--version")
        
        # Always ensure llvm-tools-preview is present if we have cargo, as it's needed for coverage
        # and installing it avoids interactive prompts during execution
        if self.status["cargo"]:
             try:
                 subprocess.run(["rustup", "component", "add", "llvm-tools-preview"], 
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
             except: pass

        if not self.status["rust_cov"] and self.status["cargo"]:
            print("[WARN] cargo-llvm-cov not found. Attempting install...")
            try:
                # Use --locked to avoid dependency breakage on older toolchains
                subprocess.run(["cargo", "install", "cargo-llvm-cov", "--locked"], check=True)
                # Re-check
                self.status["rust_cov"] = self._check_command("cargo-llvm-cov", "--version")
            except Exception as e:
                print(f"[ERROR] Failed to install cargo-llvm-cov: {e}")
                self.status["rust_cov"] = False
        
        # Linux specific coverage tools
        if sys.platform != "win32":
            self.status["lcov"] = self._check_command("lcov", "--version")
            self.status["genhtml"] = self._check_command("genhtml", "--version")
            
        return self.status

    def _check_command(self, cmd, arg):
        if shutil.which(cmd):
            return True
        
        if cmd == "OpenCppCoverage" and sys.platform == "win32":
            default_path = r"C:\Program Files\OpenCppCoverage\OpenCppCoverage.exe"
            if os.path.exists(default_path):
                os.environ["PATH"] += os.pathsep + os.path.dirname(default_path)
                return True
                
        # Check ~/.cargo/bin for rust tools (common on Linux/WSL)
        # We check this for all commands, not just those with 'cargo-'
        cargo_bin = os.path.expanduser("~/.cargo/bin")
        if os.path.exists(cargo_bin):
            if cargo_bin not in os.environ["PATH"]:
                os.environ["PATH"] += os.pathsep + cargo_bin
            # Re-check with potential new path
            if shutil.which(cmd):
                return True

        try:
            subprocess.run([cmd, arg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def print_status(self):
        print("\n--- Toolchain Status ---")
        for tool, present in self.status.items():
            icon = "[v]" if present else "[x]"
            print(f"{icon} {tool}")
