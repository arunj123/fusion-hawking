import os
import datetime
import shutil
import json

class Reporter:
    """Handles report generation and log management."""
    
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = os.path.join(root_dir, "logs", self.timestamp)
        self.latest_link = os.path.join(root_dir, "logs", "latest")
        
        # Subdirectories
        self.coverage_dir = os.path.join(self.log_dir, "coverage")
        self.raw_logs_dir = os.path.join(self.log_dir, "raw_logs")
        
        # Ensure directories exist
        os.makedirs(self.coverage_dir, exist_ok=True)
        os.makedirs(self.raw_logs_dir, exist_ok=True)
        
        # Update Symlink
        self._update_symlink()
        
        # Generate initial index.html immediately so dashboard works
        self.generate_index({})

    def _update_symlink(self):
        # Aggressively remove existing 'latest' regardless of type
        if os.path.lexists(self.latest_link):
            try:
                if os.name == 'nt':
                    # On Windows, 'rmdir' is needed for junctions, 'del' for files/symlinks
                    subprocess.run(['cmd', '/c', 'rmdir', '/q', '/s', self.latest_link], capture_output=True)
                    if os.path.lexists(self.latest_link):
                        subprocess.run(['cmd', '/c', 'del', '/f', '/q', self.latest_link], capture_output=True)
                else:
                    if os.path.isdir(self.latest_link) and not os.path.islink(self.latest_link):
                        shutil.rmtree(self.latest_link)
                    else:
                        os.remove(self.latest_link)
            except:
                pass
                
        try:
            # Try symlink first (works if Developer Mode is on)
            os.symlink(self.timestamp, self.latest_link, target_is_directory=True)
        except OSError:
            # Fallback for Windows: Junction
            if os.name == 'nt':
                import subprocess
                try:
                    # Junction target must be relative to the junction location or absolute
                    # Using absolute path for junction is often more reliable on Windows
                    abs_target = os.path.join(self.root_dir, "logs", self.timestamp)
                    subprocess.run(['cmd', '/c', 'mklink', '/J', self.latest_link, abs_target], 
                                   capture_output=True)
                except:
                    pass

    def get_log_path(self, name):
        # Categorize logs specific to subfolders for cleaner explorer
        subdir = "misc"
        if name.startswith("build_") or name.startswith("codegen_"):
            subdir = "build"
        elif name.startswith("test_") or name.startswith("rust_integration") or name.startswith("python_integration") or name.startswith("cpp_integration"):
            subdir = "test"
        elif name.startswith("demo_"):
            subdir = "demo"
        elif name.startswith("coverage_"):
            subdir = "coverage"
            
        target_dir = os.path.join(self.raw_logs_dir, subdir)
        os.makedirs(target_dir, exist_ok=True)
        return os.path.join(target_dir, f"{name}.log")

    def generate_index(self, status_data):
        """Generates the Single Page App index.html from template."""
        template_path = os.path.join(os.path.dirname(__file__), "dashboard.template.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                html = f.read()
            
            # Substitute logic
            html = html.replace("{{TIMESTAMP}}", self.timestamp)
            # Use a simpler placeholder that is valid/ignorable in JS if missed
            # We look for "null; // __INITIAL_STATUS_JSON__" or just "__INITIAL_STATUS_JSON__"
            # But let's stick to replacing the variable value.
            html = html.replace("null; // __INITIAL_STATUS_JSON__", json.dumps(status_data))
            
            # Write to timestamp directory (History)
            with open(os.path.join(self.log_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(html)
                
            # Write to logs root (Current/Global)
            # This allows http://localhost:8000/ to serve the latest run immediately
            with open(os.path.join(self.root_dir, "logs", "index.html"), "w", encoding="utf-8") as f:
                f.write(html)
                
        except Exception as e:
            print(f"Failed to generate dashboard from template: {e}")
