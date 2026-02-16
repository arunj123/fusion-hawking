const { SomeIpRuntime } = require('../src/js/dist/index.js');
const { ConsoleLogger, LogLevel } = require('../src/js/dist/logger.js');

async function main() {
    const logger = new ConsoleLogger();
    const runtime = new SomeIpRuntime(undefined, undefined, logger);

    const configPath = process.argv[2] || './tests/interop_multi_config.json';
    console.log(`[JS Client] VERSION 999`);
    console.log(`[JS Client] Loading config from ${configPath}...`);
    try {
        await runtime.loadConfigFile(configPath, 'js_client');
    } catch (err) {
        console.error(`[JS Client] Failed to load config: ${err.message}`);
        process.exit(1);
    }

    console.log("[JS Client] Starting runtime...");
    await runtime.start();

    console.log("[JS Client] Waiting for MathService (0x1234)...");

    let found = false;
    for (let i = 0; i < 20; i++) {
        const svc = runtime.getRemoteService(0x1234);
        if (svc) {
            console.log(`[JS Client] Discovered service at ${svc.address}:${svc.port}`);
            found = true;

            console.log("[JS Client] Sending RPC request...");
            const payload = Buffer.from("Hello from JS!");
            try {
                const res = await runtime.sendRequest(0x1234, 0x0001, payload, svc.address, svc.port, 5000);
                console.log(`[JS Client] Got Response: ${res.payload.toString()}`);
                process.exit(0);
            } catch (err) {
                console.error(`[JS Client] RPC Error: ${err.message}`);
                process.exit(1);
            }
            break;
        }
        await new Promise(r => setTimeout(r, 500));
    }

    if (!found) {
        console.error("[JS Client] Discovery Timeout");
        process.exit(1);
    }
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
