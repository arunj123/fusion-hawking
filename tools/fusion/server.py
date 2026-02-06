import http.server
import socketserver
import threading
import json
import os

class ProgressServer:
    def __init__(self, port=8000, report_dir="logs"):
        self.port = port
        self.report_dir = report_dir
        self.data = {"status": "INIT"}
        self.server = None
        self.thread = None

    def start(self):
        # Ensure directory exists for serving
        os.makedirs(self.report_dir, exist_ok=True)
        
        # Write initial status
        self.update(self.data)
        
        handler = http.server.SimpleHTTPRequestHandler
        # Bind to report_dir? SimpleHTTPRequestHandler serves CWD.
        # We must chdir or write a custom handler.
        # Changing CWD is risky for the main script.
        # Custom handler it is.
        
        outer_self = self # Closure scope
        
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(req_self, *args, **kwargs):
                super().__init__(*args, directory=self.report_dir, **kwargs)

            def log_message(self, format, *args):
                pass # Silence logs

            def do_GET(self):
                print(f"DEBUG: Request {self.path}")

                # Normalize /latest/api/ to /api/
                if self.path.startswith('/latest/api/'):
                    print(f"DEBUG: Normalizing API path {self.path} -> {self.path.replace('/latest/api/', '/api/')}")
                    self.path = self.path.replace('/latest/api/', '/api/')
                
                # API: Status
                if self.path == '/api/status':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    status_json = json.dumps(outer_self.data)
                    self.wfile.write(status_json.encode('utf-8'))
                    return
                
                # Explicitly serve index.html for root to avoid 404s
                if self.path == '/' or self.path == '/index.html' or self.path.startswith('/?'):
                    path = os.path.join(outer_self.report_dir, "index.html")
                    print(f"DEBUG: Serving index from {path}")
                    if os.path.exists(path):
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        with open(path, 'rb') as f:
                            self.wfile.write(f.read())
                        return
                    else:
                        print(f"Server Error: index.html not found at {path}")

                # Virtual /latest/ handling because Windows symlinks often fail/req admin
                if self.path.startswith('/latest/'):
                    real_subpath = self.path[len('/latest/'):].lstrip('/')
                    
                    # Find latest timestamp dir
                    subdirs = [d for d in os.listdir(outer_self.report_dir) 
                               if os.path.isdir(os.path.join(outer_self.report_dir, d)) and (d.isdigit() or d.startswith('20'))]
                    
                    if subdirs:
                        latest_dir = sorted(subdirs)[-1]
                        
                        # If the subpath ALREADY starts with a timestamped directory name,
                        # we should NOT prepend the latest_dir. Just serve it relative to logs/
                        first_segment = real_subpath.split('/')[0]
                        if first_segment in subdirs:
                            real_path = os.path.join(outer_self.report_dir, real_subpath)
                        else:
                            real_path = os.path.join(outer_self.report_dir, latest_dir, real_subpath)
                        
                        print(f"DEBUG: Virtual latest -> {real_path}")
                        
                        if os.path.exists(real_path) and os.path.isfile(real_path):
                             self.send_response(200)
                             ctype = self.guess_type(real_path)
                             self.send_header('Content-type', ctype)
                             self.end_headers()
                             with open(real_path, 'rb') as f:
                                 self.wfile.write(f.read())
                             return
                    else:
                        print("DEBUG: No runs found for /latest/")
                
                # API: File Explorer
                if self.path == '/api/files':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    file_list = []
                    start_path = outer_self.report_dir
                    for root, dirs, files in os.walk(start_path):
                        for f in files:
                            # Skip hidden/system files. 
                            # Only exclude index.html if it's in the root report_dir to avoid UI recursion
                            abs_root = os.path.abspath(root)
                            abs_report_dir = os.path.abspath(outer_self.report_dir)
                            is_root = (abs_root == abs_report_dir)
                            
                            if f.startswith('.') or f == 'status.json': continue
                            if is_root and f == 'index.html': continue
                            
                            full_path = os.path.join(root, f)
                            rel_path = os.path.relpath(full_path, start_path).replace("\\", "/")
                            file_list.append({
                                "path": rel_path,
                                "type": "file"
                            })
                            
                    self.wfile.write(json.dumps(file_list).encode('utf-8'))
                    return

                # Force Content-Type for logs/text to allow inline viewing
                if self.path.endswith('.log') or self.path.endswith('.txt') or self.path.endswith('.md'):
                    # standard SimpleHTTPRequestHandler sends octet-stream often for unknown types
                    # We override by calling super but updating headers? Hard with SimpleHTTPRequestHandler.
                    # Easier to just map it manually and read file.
                    f = self.send_head()
                    if f:
                        self.copyfile(f, self.wfile)
                        f.close()
                    return

                return super().do_GET()

            def do_POST(self):
                if self.path.startswith('/latest/api/'):
                    self.path = self.path.replace('/latest/api/', '/api/')

                if self.path == '/api/run':
                    content_len = int(self.headers.get('Content-Length', 0))
                    post_body = self.rfile.read(content_len)
                    data = json.loads(post_body)
                    action = data.get('action')
                    
                    print(f"Server: Received Command {action}")
                    
                    import subprocess
                    import sys
                    
                    cmd = []
                    # Map actions to main.py arguments
                    # We spawn a new process that runs the full workflow (Build -> Test)
                    # but targets specific languages.
                    # We pass --no-dashboard so it doesn't try to bind port 8000 again.
                    base_cmd = [sys.executable, "-m", "tools.fusion.main", "--no-dashboard"]
                    
                    if action == 'test_rust':
                        cmd = base_cmd + ["--target", "rust"]
                    elif action == 'test_python':
                        cmd = base_cmd + ["--target", "python"]
                    elif action == 'test_cpp':
                        cmd = base_cmd + ["--target", "cpp"]
                    elif action == 'run_demos':
                        cmd = base_cmd # Default runs demos unless skipped
                    
                    if cmd:
                        try:
                            # Run in background/new console
                            # On Windows, creationflags=subprocess.CREATE_NEW_CONSOLE might help debugging
                            # but we want it to just run.
                            subprocess.Popen(cmd, cwd=os.getcwd())
                            
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b'{"status": "OK"}')
                        except Exception as e:
                            self.send_response(500)
                            self.end_headers()
                            self.wfile.write(f'{{"status": "ERROR", "message": "{str(e)}"}}'.encode())
                    else:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b'{"status": "UNKNOWN_ACTION"}')
                    return

            def guess_type(self, path):
                # Ensure logs and source code are treated as text for inline viewing
                exts = [".log", ".txt", ".md", ".rs", ".py", ".cpp", ".c", ".h", ".hpp", ".toml", ".json", ".xml", ".cmake"]
                if any(path.endswith(e) for e in exts):
                    return "text/plain"
                return super().guess_type(path)


        
        # Port Scanning
        start_port = self.port
        self.server = None
        for p in range(start_port, start_port + 10):
            try:
                self.server = socketserver.TCPServer(("", p), Handler)
                self.port = p
                break
            except OSError:
                continue
        
        if self.server:
            self.thread = threading.Thread(target=self.server.serve_forever)
            self.thread.daemon = True
            self.thread.start()
            print(f"📊 Dashboard Link: http://localhost:{self.port}")
        else:
            print(f"⚠️ Could not start dashboard. Ports {start_port}-{start_port+9} are busy.")

    def update(self, data):
        self.data.update(data)
        # Write to status.json for persistence/fallback
        path = os.path.join(self.report_dir, "status.json")
        try:
            with open(path, "w") as f:
                json.dump(self.data, f)
        except:
            pass
            
    def stop(self):
        if self.server:
            self.server.shutdown()
