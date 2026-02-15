
import { SomeIpRuntime, LogLevel, MessageType, ReturnCode } from 'fusion-hawking';
import { MathServiceClient, StringServiceClient } from './dist/manual_bindings.js';

const configPath = process.argv[2];
const instanceName = process.argv[3];
const runtime = new SomeIpRuntime(configPath, instanceName);
runtime.start();
(async () => {

            // Wait for SD
            let found = false;
            for (let i = 0; i < 20; i++) {
                const svc = runtime.getRemoteService(0x1001);
                if (svc) {
                    console.log(`FOUND_SERVICE_AT: ${svc.address}:${svc.port}`);
                    found = true;
                    break;
                }
                await new Promise(r => setTimeout(r, 1000));
            }

            if (!found) {
                console.log("JS_ERROR: Service 0x1001 not found");
                process.exit(1);
            }
            
            try {
                const client = new MathServiceClient(runtime, 'js_client');
                const result = await client.add(10, 20);
                console.log(`JS_RESULT: ${result}`);
            } catch (e) {
                console.log(`JS_ERROR: ${e.message}`);
            }
            
})().catch(e => {
    console.log(`JS_ERROR: ${e.message}`);
    process.exit(1);
}).finally(() => {
    runtime.stop();
});
