
import dgram from 'node:dgram';
import { deserializeHeader, serializeHeader, MessageType, ReturnCode } from '../../../../src/js/dist/index.js';

const PORT = 40001;
const HOST = '127.0.0.1';
const client = dgram.createSocket('udp4');

const payload = Buffer.from('Hello from JS');
const header = serializeHeader({
    serviceId: 0x1234,
    methodId: 0x0001,
    length: payload.length + 8,
    clientId: 0x99,
    sessionId: 1,
    protocolVersion: 1,
    interfaceVersion: 1,
    messageType: MessageType.REQUEST,
    returnCode: ReturnCode.OK
});

const message = Buffer.concat([header, payload]);

client.on('message', (msg, rinfo) => {
    console.log(`client got: ${msg.length} bytes from ${rinfo.address}:${rinfo.port}`);
    const h = deserializeHeader(msg);
    if (h && h.messageType === MessageType.RESPONSE) {
        const p = msg.subarray(16).toString();
        console.log(`Success: Received '${p}'`);
        client.close();
    }
});

client.send(message, PORT, HOST, (err) => {
    if (err) {
        console.error(err);
        client.close();
    } else {
        console.log('Sent Request');
    }
});

// Timeout
setTimeout(() => {
    console.log('Timeout waiting for response');
    client.close();
}, 2000);
