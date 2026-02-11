/**
 * Codec Tests — SOME/IP Header & Primitive Serialization
 * Uses Node.js built-in test runner (node --test).
 * AUTOSAR R22-11 spec references in assertions.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    HEADER_SIZE, MessageType, ReturnCode, SessionIdManager,
    deserializeHeader, serializeHeader, buildPacket,
    serializeInt32, serializeString, serializeList,
    deserializeInt32, deserializeString, deserializeBool,
    serializeBool, serializeFloat32, deserializeFloat32,
    serializeInt8, serializeInt16, serializeInt64,
    serializeUInt8, serializeUInt16, serializeUInt32, serializeUInt64,
    deserializeInt8, deserializeInt16, deserializeInt64,
    deserializeUInt8, deserializeUInt16, deserializeUInt32, deserializeUInt64,
    deserializeFloat64, serializeFloat64,
} from '../dist/codec.js';

describe('SOME/IP Header', () => {
    it('[PRS_SOMEIP_00030] header is 16 bytes', () => {
        assert.equal(HEADER_SIZE, 16);
    });

    it('serializes and deserializes a request header', () => {
        const header = {
            serviceId: 0x1001,
            methodId: 0x0001,
            length: 16,
            clientId: 0,
            sessionId: 1,
            protocolVersion: 0x01,
            interfaceVersion: 0x01,
            messageType: MessageType.REQUEST,
            returnCode: ReturnCode.OK,
        };
        const buf = serializeHeader(header);
        assert.equal(buf.length, 16);
        const parsed = deserializeHeader(buf);
        assert.notEqual(parsed, null);
        assert.equal(parsed.serviceId, 0x1001);
        assert.equal(parsed.methodId, 0x0001);
        assert.equal(parsed.protocolVersion, 0x01, '[PRS_SOMEIP_00032]');
        assert.equal(parsed.messageType, MessageType.REQUEST);
        assert.equal(parsed.returnCode, ReturnCode.OK);
    });

    it('returns null for truncated packet', () => {
        const buf = Buffer.alloc(8);
        assert.equal(deserializeHeader(buf), null);
    });

    it('[PRS_SOMEIP_00034] message type enum values match spec', () => {
        assert.equal(MessageType.REQUEST, 0x00);
        assert.equal(MessageType.REQUEST_NO_RETURN, 0x01);
        assert.equal(MessageType.NOTIFICATION, 0x02);
        assert.equal(MessageType.RESPONSE, 0x80);
        assert.equal(MessageType.ERROR, 0x81);
        assert.equal(MessageType.REQUEST_WITH_TP, 0x20);
        assert.equal(MessageType.RESPONSE_WITH_TP, 0xA0);
    });

    it('[PRS_SOMEIP_00043] return code enum values match spec', () => {
        assert.equal(ReturnCode.OK, 0x00);
        assert.equal(ReturnCode.NOT_OK, 0x01);
        assert.equal(ReturnCode.UNKNOWN_SERVICE, 0x02);
        assert.equal(ReturnCode.UNKNOWN_METHOD, 0x03);
        assert.equal(ReturnCode.NOT_READY, 0x04);
        assert.equal(ReturnCode.WRONG_PROTOCOL_VERSION, 0x07);
        assert.equal(ReturnCode.WRONG_INTERFACE_VERSION, 0x08);
        assert.equal(ReturnCode.MALFORMED_MESSAGE, 0x09);
    });
});

describe('buildPacket', () => {
    it('builds a complete request packet', () => {
        const payload = Buffer.from([0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x03]);
        const pkt = buildPacket(0x1001, 0x0001, 1, MessageType.REQUEST, payload);
        assert.equal(pkt.length, 24);
        const h = deserializeHeader(pkt);
        assert.equal(h.serviceId, 0x1001);
        assert.equal(h.length, 16); // 8 header part2 + 8 payload
    });
});

describe('SessionIdManager', () => {
    it('increments session IDs per service/method pair', () => {
        const mgr = new SessionIdManager();
        assert.equal(mgr.nextSessionId(0x1001, 0x0001), 1);
        assert.equal(mgr.nextSessionId(0x1001, 0x0001), 2);
        assert.equal(mgr.nextSessionId(0x1001, 0x0001), 3);
        // Different pair starts at 1
        assert.equal(mgr.nextSessionId(0x2002, 0x0001), 1);
    });

    it('wraps around at 0xFFFF', () => {
        const mgr = new SessionIdManager();
        // Simulate near-wrap
        for (let i = 0; i < 0xFFFF; i++) mgr.nextSessionId(0x1001, 0x01);
        const wrapped = mgr.nextSessionId(0x1001, 0x01);
        assert.equal(wrapped, 1, 'Should wrap to 1 after 0xFFFF');
    });

    it('reset clears specific pair', () => {
        const mgr = new SessionIdManager();
        mgr.nextSessionId(0x1001, 0x01);
        mgr.nextSessionId(0x1001, 0x01);
        mgr.reset(0x1001, 0x01);
        assert.equal(mgr.nextSessionId(0x1001, 0x01), 1);
    });
});

describe('Primitive Serialization', () => {
    it('int32 round-trip', () => {
        const buf = serializeInt32(42);
        assert.equal(buf.length, 4);
        assert.equal(deserializeInt32(buf, 0).value, 42);
    });

    it('negative int32', () => {
        const buf = serializeInt32(-100);
        assert.equal(deserializeInt32(buf, 0).value, -100);
    });

    it('int8 round-trip', () => {
        const buf = serializeInt8(-5);
        assert.equal(deserializeInt8(buf, 0).value, -5);
        assert.equal(deserializeInt8(buf, 0).bytesRead, 1);
    });

    it('int16 round-trip', () => {
        const buf = serializeInt16(-1000);
        assert.equal(deserializeInt16(buf, 0).value, -1000);
        assert.equal(deserializeInt16(buf, 0).bytesRead, 2);
    });

    it('int64 round-trip', () => {
        const buf = serializeInt64(BigInt("9223372036854775807"));
        assert.equal(deserializeInt64(buf, 0).value, BigInt("9223372036854775807"));
        assert.equal(deserializeInt64(buf, 0).bytesRead, 8);
    });

    it('uint8 round-trip', () => {
        const buf = serializeUInt8(255);
        assert.equal(deserializeUInt8(buf, 0).value, 255);
    });

    it('uint16 round-trip', () => {
        const buf = serializeUInt16(65535);
        assert.equal(deserializeUInt16(buf, 0).value, 65535);
    });

    it('uint32 round-trip', () => {
        const buf = serializeUInt32(0xDEADBEEF);
        assert.equal(deserializeUInt32(buf, 0).value, 0xDEADBEEF);
    });

    it('uint64 round-trip', () => {
        const buf = serializeUInt64(BigInt("18446744073709551615"));
        assert.equal(deserializeUInt64(buf, 0).value, BigInt("18446744073709551615"));
    });

    it('string round-trip', () => {
        const buf = serializeString('Hello, SOME/IP!');
        const result = deserializeString(buf, 0);
        assert.equal(result.value, 'Hello, SOME/IP!');
        assert.equal(result.bytesRead, 4 + 15);
    });

    it('empty string', () => {
        const buf = serializeString('');
        const result = deserializeString(buf, 0);
        assert.equal(result.value, '');
        assert.equal(result.bytesRead, 4);
    });

    it('unicode string', () => {
        const buf = serializeString('こんにちは');
        const result = deserializeString(buf, 0);
        assert.equal(result.value, 'こんにちは');
    });

    it('bool round-trip', () => {
        const t = serializeBool(true);
        const f = serializeBool(false);
        assert.equal(deserializeBool(t, 0).value, true);
        assert.equal(deserializeBool(f, 0).value, false);
    });

    it('float32 round-trip', () => {
        const buf = serializeFloat32(3.14);
        const result = deserializeFloat32(buf, 0);
        assert.ok(Math.abs(result.value - 3.14) < 0.01);
    });

    it('float64 round-trip', () => {
        const buf = serializeFloat64(3.141592653589793);
        const result = deserializeFloat64(buf, 0);
        assert.equal(result.value, 3.141592653589793);
    });

    it('list serialization', () => {
        const items = [10, 20, 30].map(v => serializeInt32(v));
        const buf = serializeList(items);
        assert.equal(buf.length, 4 + 12); // 4-byte length + 3*4 bytes
        assert.equal(buf.readUInt32BE(0), 12); // byte length
    });
});

describe('Golden Byte References', () => {
    it('[PRS_SOMEIP_00030] matches golden request hex', () => {
        const golden = Buffer.from(
            '1001000100000010000000010101000000000005' + '00000003', 'hex');
        const h = deserializeHeader(golden);
        assert.notEqual(h, null);
        assert.equal(h.serviceId, 0x1001);
        assert.equal(h.methodId, 0x0001);
        assert.equal(h.length, 16);
        assert.equal(h.protocolVersion, 0x01);
        assert.equal(h.messageType, MessageType.REQUEST);
        assert.equal(h.returnCode, ReturnCode.OK);
        // Payload
        assert.equal(golden.readInt32BE(16), 5);
        assert.equal(golden.readInt32BE(20), 3);
    });

    it('[PRS_SOMEIP_00030] matches golden response hex', () => {
        const golden = Buffer.from(
            '100100010000000c000000010101800000000008', 'hex');
        const h = deserializeHeader(golden);
        assert.equal(h.messageType, MessageType.RESPONSE);
        assert.equal(golden.readInt32BE(16), 8);
    });

    it('[PRS_SOMEIP_00030] matches golden notification hex', () => {
        const golden = Buffer.from(
            '100180010000000c000000010101020000000064', 'hex');
        const h = deserializeHeader(golden);
        assert.equal(h.messageType, MessageType.NOTIFICATION);
        assert.ok(h.methodId & 0x8000, 'Event IDs have bit 15 set');
    });
});
