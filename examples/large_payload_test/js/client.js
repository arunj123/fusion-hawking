import { SomeIpRuntime } from '../../../src/js/dist/runtime.js';
import { ConsoleLogger, LogLevel } from '../../../src/js/dist/logger.js';
import { loadConfig } from '../../../src/js/dist/config.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const args = process.argv.slice(2);
const configPath = args[0] ? path.resolve(args[0]) : path.join(__dirname, '../config_rust.json');

async function main() {
    console.log("Starting JS TP Client...");
    const logger = new ConsoleLogger(LogLevel.DEBUG);
    const runtime = new SomeIpRuntime(undefined, undefined, logger);

    // Load and patch config
    const config = loadConfig(configPath, "tp_client");

    // Force wildcard for testing if needed
    if (config.interfaces && config.interfaces["lo_alias"] && config.interfaces["lo_alias"].endpoints["client_endpoint"]) {
        console.log("Patching client_endpoint to 0.0.0.0");
        config.interfaces["lo_alias"].endpoints["client_endpoint"].ip = "0.0.0.0";
    }

    runtime.setConfig(config);
    await runtime.start();

    console.log("Waiting for service 0x5000...");

    // Wait for service offer (10s)
    let service = undefined;
    for (let i = 0; i < 20; i++) {
        service = runtime.getRemoteService(0x5000, 1);
        if (service) break;
        await new Promise(r => setTimeout(r, 500));
    }

    if (!service) {
        console.error("Service 0x5000 not found!");
        process.exit(1);
    }

    console.log(`Service found at ${service.address}:${service.port}`);

    // 1. GET Request
    console.log("Sending GET (0x0001)...");
    try {
        const resp = await runtime.sendRequest(0x5000, 0x0001, Buffer.alloc(0), service.address, service.port);
        console.log(`Received Response size: ${resp.payload.length}`);
        if (resp.payload.length === 5000) {
            console.log("SUCCESS: Received 5000 bytes!");
            // Verify
            let ok = true;
            for (let i = 0; i < resp.payload.length; i++) {
                if (resp.payload[i] !== (i % 256)) {
                    console.log(`ERROR: Mismatch at index ${i} expected ${i % 256} got ${resp.payload[i]}`);
                    ok = false;
                    break;
                }
            }
            if (ok) console.log("SUCCESS: Content Verified.");
        } else {
            console.log(`FAILURE: Expected 5000 bytes. Got ${resp.payload.length}`);
        }
    } catch (e) {
        console.error("GET Request Failed:", e);
    }

    // 2. ECHO Request
    console.log("Sending ECHO (0x0002)...");
    try {
        const payload = Buffer.alloc(5000);
        for (let i = 0; i < 5000; i++) payload[i] = i % 256;

        const resp = await runtime.sendRequest(0x5000, 0x0002, payload, service.address, service.port);
        console.log(`Received ECHO Response size: ${resp.payload.length}`);
        if (resp.payload.length === 5000) {
            console.log("SUCCESS: ECHO Received 5000 bytes!");
            // Verify
            let ok = true;
            for (let i = 0; i < resp.payload.length; i++) {
                if (resp.payload[i] !== (i % 256)) {
                    console.log(`ERROR: ECHO Mismatch at index ${i} expected ${i % 256} got ${resp.payload[i]}`);
                    ok = false;
                    break;
                }
            }
            if (ok) console.log("SUCCESS: ECHO Content Verified.");
        } else {
            console.log(`FAILURE: Expected 5000 bytes. Got ${resp.payload.length}`);
        }
    } catch (e) {
        console.error("ECHO Request Failed:", e);
    }

    runtime.stop();
}

main().catch(e => {
    console.error(e);
    process.exit(1);
});
