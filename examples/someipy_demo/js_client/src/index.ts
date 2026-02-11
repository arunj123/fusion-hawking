/**
 * Fusion Hawking JS Client for someipy Echo interop demo.
 *
 * Discovers the someipy service (0x1234) via Service Discovery,
 * sends an Echo request, and prints the response.
 */
import { SomeIpRuntime, ReturnCode } from 'fusion-hawking';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SERVICE_ID = 0x1234;
const METHOD_ECHO = 0x0001;

async function main(): Promise<void> {
    const configPath = path.join(__dirname, '..', '..', 'client_config.json');

    const runtime = new SomeIpRuntime();
    await runtime.loadConfigFile(configPath, 'js_client');
    await runtime.start();

    const logger = runtime.getLogger();

    logger.log(0, 'JSClient', `[Fusion JS Client] Waiting for someipy service (0x${SERVICE_ID.toString(16)})...`);

    // Wait for SD to discover the service (up to 8 seconds)
    let svc = runtime.getRemoteService(SERVICE_ID);
    for (let i = 0; i < 16 && !svc; i++) {
        await new Promise(r => setTimeout(r, 500));
        svc = runtime.getRemoteService(SERVICE_ID);
    }

    if (!svc) {
        console.log('[Fusion JS Client] Could not discover service.');
        await runtime.stop();
        process.exit(1);
    }

    const message = 'Hello from Fusion JS!';
    console.log(`[Fusion JS Client] Sending Echo: '${message}'`);

    const payload = Buffer.from(message, 'utf-8');
    try {
        const response = await runtime.sendRequest(
            SERVICE_ID,
            METHOD_ECHO,
            payload,
            svc.address,
            svc.port,
            5000,
        );

        if (response.returnCode === ReturnCode.OK) {
            const text = response.payload.toString('utf-8');
            console.log(`[Fusion JS Client] Got Response: '${text}'`);
        } else {
            console.log(`[Fusion JS Client] Error: return code ${response.returnCode}`);
        }
    } catch (e: any) {
        console.log(`[Fusion JS Client] Request failed: ${e.message}`);
    }

    await runtime.stop();
}

main().catch(console.error);
