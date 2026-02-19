import os
import sys
import tempfile
import shutil
from .execution import AppRunner
from .config_gen import ConfigGenerator

class IntegrationTestContext:
    """
    Manages a temporary environment for an integration test.
    Handles config generation, process tracking, and log management.
    """
    def __init__(self, name, base_log_dir=None):
        self.name = name
        self.base_log_dir = base_log_dir or os.environ.get("FUSION_LOG_DIR") or os.path.join(os.getcwd(), "logs", "integration")
        self.log_dir = os.path.join(self.base_log_dir, name)
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.config_gen = ConfigGenerator()
        self.runners = []
        self.temp_files = []

    def add_runner(self, name, cmd, cwd=None, env=None, ns=None, use_sudo=False):
        runner = AppRunner(name, cmd, self.log_dir, cwd=cwd, env=env, ns=ns, use_sudo=use_sudo)
        self.runners.append(runner)
        return runner

    def run_python_code(self, code, name, ns=None, env=None):
        """Generates a temporary Python script and runs it."""
        fd, path = tempfile.mkstemp(suffix='.py', prefix=f"tmp_{name}_", dir=self.log_dir)
        os.close(fd)
        with open(path, 'w') as f:
            f.write(code)
        
        self.temp_files.append(path)
        cmd = [sys.executable, "-u", path]
        runner = self.add_runner(name, cmd, ns=ns, env=env)
        runner.start()
        return runner

    def run_js_code(self, js_code, config_path, instance_name, js_app_dir, ns=None):
        """Generates a temporary JS script and runs it using node."""
        path = os.path.join(js_app_dir, f"tmp_{instance_name}_{self.name}.mjs")
        
        # Ensure manual bindings are present (either pre-built or built now)
        dist_dir = os.path.join(js_app_dir, "dist")
        if not os.path.exists(dist_dir) or not os.listdir(dist_dir):
             print(f"[info] JS dist missing in {js_app_dir}. Building...")
             os.makedirs(js_app_dir, exist_ok=True)
             npm = "npm.cmd" if sys.platform == "win32" else "npm"
             subprocess.run([npm, "install"], cwd=js_app_dir, capture_output=True)
             subprocess.run([npm, "run", "build"], cwd=js_app_dir, capture_output=True)

        wrapper = f"""
import {{ SomeIpRuntime }} from 'fusion-hawking';
import * as manual_bindings from './dist/manual_bindings.js';
const MathServiceClient = manual_bindings.MathServiceClient;

const configPath = process.argv[2];
const instanceName = process.argv[3];
const runtime = new SomeIpRuntime(configPath, instanceName);
runtime.start();
(async () => {{
{js_code}
}})().catch(e => {{
    console.log(`JS_ERROR: ${{e.message}}`);
    process.exit(1);
}}).finally(() => {{
    runtime.stop();
}});
"""
        with open(path, 'w') as f:
            f.write(wrapper)
        
        self.temp_files.append(path)
        # In ESM mode, we must pass the path correctly. basename might not be enough if cwd is different?
        # But we set cwd=js_app_dir below, so basename is fine.
        cmd = ["node", os.path.basename(path), config_path, instance_name]
        runner = self.add_runner(instance_name, cmd, cwd=js_app_dir, ns=ns)
        runner.start()
        return runner

    def get_runner(self, name):
        """Retrieves a runner by its name."""
        for r in self.runners:
            if r.name == name:
                return r
        return None

    def cleanup(self):
        """Stops all runners and cleans up temp files."""
        for r in self.runners:
            r.stop()
        
        for f in self.temp_files:
            try:
                os.remove(f)
            except:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
