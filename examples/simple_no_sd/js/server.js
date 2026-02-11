
import dgram from 'node:dgram';
import { deserializeHeader, serializeHeader, MessageType, ReturnCode } from '../../../../src/js/dist/index.js';

const PORT = 40001;
const server = dgram.createSocket('udp4');

server.on('error', (err) => {
    console.error(`server error:\n${err.stack}`);
    server.close();
});

server.on('message', (msg, rinfo) => {
    console.log(`server got: ${msg.length} bytes from ${rinfo.address}:${rinfo.port}`);

    try {
        const header = deserializeHeader(msg);
        if (!header) {
            console.log('Invalid header');
            return;
        }

        console.log(`header: service=0x${header.serviceId.toString(16)} method=0x${header.methodId.toString(16)} type=${header.messageType}`);

        if (header.messageType === MessageType.REQUEST || header.messageType === MessageType.REQUEST_NO_RETURN) {
            // Send Response
            const payload = Buffer.from('JS OK');
            const resHeader = serializeHeader({
                serviceId: header.serviceId,
                methodId: header.methodId,
                length: payload.length + 8,
                clientId: header.clientId,
                sessionId: header.sessionId,
                protocolVersion: header.protocolVersion,
                interfaceVersion: header.interfaceVersion,
                messageType: MessageType.RESPONSE,
                returnCode: ReturnCode.OK
            });

            const response = Buffer.concat([resHeader, payload]);
            server.send(response, rinfo.port, rinfo.address, (err) => {
                if (err) console.error('Error sending response:', err);
                else console.log('Sent response');
            });
        }
    } catch (e) {
        console.error('Error processing message:', e);
    }
});

server.on('listening', () => {
    const address = server.address();
    console.log(`Simple JS Server listening ${address.address}:${address.port}`);
});

server.bind(PORT);
