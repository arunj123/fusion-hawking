
import { SomeIpRuntime, LogLevel } from 'fusion-hawking';
import * as path from 'path';
import { MathServiceClient, StringServiceClient } from './manual_bindings.js';

async function main() {
    console.log("=== Integrated JS Application ===");

    // Path to config in parent directory
    const defaultPath = path.resolve('../config.json');
    const configPath = process.argv[2] ? path.resolve(process.argv[2]) : defaultPath;
    console.log(`Using config from: ${configPath}`);
    // Using instance name 'js_app_instance' - make sure it's in config or we add it
    // If not in config, runtime might fail to start listener but can still be client?
    // Actually runtime requires config entry for "own" instance to bind ports.
    // For now we assume we use a dynamic client or borrow an existing instance configuration for testing?
    // Or we rely on client-only mode if runtime supports it.
    // Our Runtime currently binds UDP based on instance config.
    // We'll use 'python_app_instance' config for now if we don't assume we can modify config.json
    // But two apps on same port = clash.
    // We should Add 'js_app_instance' to config.json.

    // For this example, we'll try to use a unique instance name and hope config patching adds it or we add it now.
    // TODO: We must check config.json content.

    // Wait, let's assume 'js_app_instance' is needed.
    const runtime = new SomeIpRuntime();
    // Load configuration
    await runtime.loadConfigFile(configPath, 'js_app_instance');

    runtime.getLogger().log(LogLevel.INFO, "Main", "JS Runtime Starting...");
    runtime.start();

    // Allow time for SD
    await new Promise(r => setTimeout(r, 2000));

    // 1. Call Rust Math Service
    try {
        const mathClient = new MathServiceClient(runtime, 'math-client');
        // 'math-client' must be in config too...

        runtime.getLogger().log(LogLevel.INFO, "Client", "Calling Math.Add(10, 20)...");
        // Note: getClient in JS runtime currently mimics C++ where you pass alias?
        // Actually JS runtime doesn't have high level 'getClient' that returns typed stub yet.
        // We use manual bindings passing runtime.

        // We need to ensure 'math-client' alias exists in config.json pointing to service 0x1001.

        const result = await mathClient.add(10, 20);
        runtime.getLogger().log(LogLevel.INFO, "Client", `Result: ${result}`);
    } catch (e) {
        runtime.getLogger().log(LogLevel.ERROR, "Client", `Math Failed: ${e}`);
    }

    // 2. Call Python String Service
    try {
        const stringClient = new StringServiceClient(runtime, 'string-client');
        runtime.getLogger().log(LogLevel.INFO, "Client", "Calling String.Reverse('Hello JS')...");
        const rev = await stringClient.reverse('Hello JS');
        runtime.getLogger().log(LogLevel.INFO, "Client", `Result: '${rev}'`);
    } catch (e) {
        runtime.getLogger().log(LogLevel.ERROR, "Client", `String Failed: ${e}`);
    }

    // Keep alive
    setTimeout(() => {
        runtime.stop();
        process.exit(0);
    }, 5000);
}

main().catch(console.error);
