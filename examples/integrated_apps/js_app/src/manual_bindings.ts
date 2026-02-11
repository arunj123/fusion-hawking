
import { SomeIpRuntime, MessageType, ReturnCode } from 'fusion-hawking';

// 0x1001: MathService
export class MathServiceClient {
    constructor(private runtime: SomeIpRuntime, private instance: string) { }

    public async add(a: number, b: number): Promise<number> {
        const serviceId = 0x1001;
        const methodId = 1;

        // Resolve service
        const svc = this.runtime.getRemoteService(serviceId, 1);
        if (!svc) throw new Error(`Service 0x${serviceId.toString(16)} not found`);

        // Serialize Args: 2 x int32 (Big Endian)
        const payload = Buffer.alloc(8);
        payload.writeInt32BE(a, 0);
        payload.writeInt32BE(b, 4);

        const response = await this.runtime.sendRequest(
            serviceId,
            methodId,
            payload,
            svc.address,
            svc.port
        );

        if (response.returnCode !== ReturnCode.OK) {
            throw new Error(`RPC Error: ${response.returnCode}`);
        }

        // Deserialize Result: int32
        return response.payload.readInt32BE(0);
    }
}

// 0x2001: StringService
export class StringServiceClient {
    constructor(private runtime: SomeIpRuntime, private instance: string) { }

    public async reverse(text: string): Promise<string> {
        const serviceId = 0x2001;
        const methodId = 1;

        // Resolve service
        const svc = this.runtime.getRemoteService(serviceId, 1);
        if (!svc) throw new Error(`Service 0x${serviceId.toString(16)} not found`);

        // Serialize String: Length (32-bit) + Bytes + Null? (Spec depends, usually just bytes for string type in our IDL)
        // Check IDL.md: "4-byte length prefix + UTF-8 bytes"
        const strBytes = Buffer.from(text, 'utf8');
        const payload = Buffer.alloc(4 + strBytes.length);
        payload.writeUInt32BE(strBytes.length, 0);
        strBytes.copy(payload, 4);

        const response = await this.runtime.sendRequest(
            serviceId,
            methodId,
            payload,
            svc.address,
            svc.port
        );

        if (response.returnCode !== ReturnCode.OK) {
            throw new Error(`RPC Error: ${response.returnCode}`);
        }

        // Deserialize String
        const len = response.payload.readUInt32BE(0);
        return response.payload.slice(4, 4 + len).toString('utf8');
    }
}
