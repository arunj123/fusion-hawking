import test from 'node:test';
import assert from 'node:assert';
import { TcpTransport, TcpServerTransport } from '../dist/transport.js';

test('TCP Transport: Client-Server Loopback', async (t) => {
    const server = new TcpServerTransport();
    const client = new TcpTransport();

    let serverRecv = false;
    let clientRecv = false;

    // SOME/IP Message: 16-byte header + 4-byte payload
    // Header: Sid=0x1234, Mid=0x5678, Len=12 (8+4), CID=0x0001, SSID=0x0001, PV=1, IV=1, MT=0, RC=0
    const packet = Buffer.from([
        0x12, 0x34, 0x56, 0x78, // Message ID
        0x00, 0x00, 0x00, 0x0C, // Length (8 + payload size)
        0x00, 0x01, 0x00, 0x01, // Request ID
        0x01, 0x01, 0x00, 0x00, // Version/Type/Return
        0xAA, 0xBB, 0xCC, 0xDD  // Payload
    ]);

    await server.bind('127.0.0.1', 0);
    const port = server.localPort;

    server.onMessage((data, rinfo) => {
        assert.strictEqual(data.length, packet.length);
        assert.deepStrictEqual(data, packet);
        serverRecv = true;
        // Echo back
        server.send(data, rinfo.address, rinfo.port);
    });

    await client.connect('127.0.0.1', port);
    client.onMessage((data, rinfo) => {
        assert.strictEqual(data.length, packet.length);
        assert.deepStrictEqual(data, packet);
        clientRecv = true;
    });

    await client.send(packet, '127.0.0.1', port);

    // Wait for message exchange
    for (let i = 0; i < 20; i++) {
        if (serverRecv && clientRecv) break;
        await new Promise(r => setTimeout(r, 100));
    }

    assert.ok(serverRecv, 'Server should have received packet');
    assert.ok(clientRecv, 'Client should have received echoed packet');

    client.close();
    server.close();
});

test('TCP Transport: Multi-Packet Framing', async (t) => {
    const server = new TcpServerTransport();
    const client = new TcpTransport();

    let packetsRecv = 0;

    const packet1 = Buffer.from([
        0x00, 0x01, 0x00, 0x01, // Message ID
        0x00, 0x00, 0x00, 0x09, // Length (8 + 1)
        0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x00, 0x00,
        0x11
    ]);
    const packet2 = Buffer.from([
        0x00, 0x02, 0x00, 0x02, // Message ID
        0x00, 0x00, 0x00, 0x0A, // Length (8 + 2)
        0x00, 0x02, 0x00, 0x02, 0x01, 0x01, 0x00, 0x00,
        0x22, 0x33
    ]);

    await server.bind('127.0.0.1', 0);
    const port = server.localPort;

    server.onMessage((data, rinfo) => {
        packetsRecv++;
    });

    await client.connect('127.0.0.1', port);

    // Send both packets together in one TCP write
    await client.send(Buffer.concat([packet1, packet2]), '127.0.0.1', port);

    for (let i = 0; i < 10; i++) {
        if (packetsRecv === 2) break;
        await new Promise(r => setTimeout(r, 100));
    }

    assert.strictEqual(packetsRecv, 2, 'Should have received exactly 2 framed packets');

    client.close();
    server.close();
});
