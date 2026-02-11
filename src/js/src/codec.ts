/**
 * Fusion Hawking SOME/IP Codec — Header parsing and serialization
 * 
 * Implements AUTOSAR R22-11 [PRS_SOMEIP_00030] header format and
 * primitive type serialization per SOME/IP wire format.
 * 
 * All multi-byte values use big-endian (network byte order).
 * @module
 */

/** SOME/IP Header size in bytes [PRS_SOMEIP_00030]. */
export const HEADER_SIZE = 16;

/** SOME/IP Message Types [PRS_SOMEIP_00034]. */
export enum MessageType {
    REQUEST = 0x00,
    REQUEST_NO_RETURN = 0x01,
    NOTIFICATION = 0x02,
    REQUEST_WITH_TP = 0x20,
    REQUEST_NO_RETURN_WITH_TP = 0x21,
    NOTIFICATION_WITH_TP = 0x22,
    RESPONSE = 0x80,
    ERROR = 0x81,
    RESPONSE_WITH_TP = 0xA0,
    ERROR_WITH_TP = 0xA1,
}

/** SOME/IP Return Codes [PRS_SOMEIP_00043]. */
export enum ReturnCode {
    OK = 0x00,
    NOT_OK = 0x01,
    UNKNOWN_SERVICE = 0x02,
    UNKNOWN_METHOD = 0x03,
    NOT_READY = 0x04,
    NOT_REACHABLE = 0x05,
    TIMEOUT = 0x06,
    WRONG_PROTOCOL_VERSION = 0x07,
    WRONG_INTERFACE_VERSION = 0x08,
    MALFORMED_MESSAGE = 0x09,
    WRONG_MESSAGE_TYPE = 0x0A,
    E2E_REPEATED = 0x0B,
    E2E_WRONG_SEQUENCE = 0x0C,
    E2E_NOT_AVAILABLE = 0x0D,
    E2E_NO_NEW_DATA = 0x0E,
}

/** Parsed SOME/IP header. */
export interface SomeIpHeader {
    serviceId: number;
    methodId: number;
    length: number;
    clientId: number;
    sessionId: number;
    protocolVersion: number;
    interfaceVersion: number;
    messageType: MessageType;
    returnCode: ReturnCode;
}

/** Session ID manager — tracks per (serviceId, methodId) pair. */
export class SessionIdManager {
    private counters = new Map<string, number>();

    private key(serviceId: number, methodId: number): string {
        return `${serviceId}:${methodId}`;
    }

    nextSessionId(serviceId: number, methodId: number): number {
        const k = this.key(serviceId, methodId);
        const current = this.counters.get(k) ?? 0;
        const next = current >= 0xFFFF ? 1 : current + 1;
        this.counters.set(k, next);
        return next;
    }

    reset(serviceId: number, methodId: number): void {
        this.counters.set(this.key(serviceId, methodId), 0);
    }

    resetAll(): void {
        this.counters.clear();
    }
}

/**
 * Deserialize a SOME/IP header from a Buffer.
 * Returns null if buffer is too short (< 16 bytes).
 */
export function deserializeHeader(buf: Buffer): SomeIpHeader | null {
    if (buf.length < HEADER_SIZE) return null;
    return {
        serviceId: buf.readUInt16BE(0),
        methodId: buf.readUInt16BE(2),
        length: buf.readUInt32BE(4),
        clientId: buf.readUInt16BE(8),
        sessionId: buf.readUInt16BE(10),
        protocolVersion: buf[12],
        interfaceVersion: buf[13],
        messageType: buf[14] as MessageType,
        returnCode: buf[15] as ReturnCode,
    };
}

/**
 * Serialize a SOME/IP header into a new Buffer (16 bytes).
 */
export function serializeHeader(h: SomeIpHeader): Buffer {
    const buf = Buffer.alloc(HEADER_SIZE);
    buf.writeUInt16BE(h.serviceId, 0);
    buf.writeUInt16BE(h.methodId, 2);
    buf.writeUInt32BE(h.length, 4);
    buf.writeUInt16BE(h.clientId, 8);
    buf.writeUInt16BE(h.sessionId, 10);
    buf[12] = h.protocolVersion;
    buf[13] = h.interfaceVersion;
    buf[14] = h.messageType;
    buf[15] = h.returnCode;
    return buf;
}

/**
 * Build a complete SOME/IP packet (header + payload).
 */
export function buildPacket(
    serviceId: number,
    methodId: number,
    sessionId: number,
    messageType: MessageType,
    payload: Buffer,
    opts?: { clientId?: number; protocolVersion?: number; interfaceVersion?: number; returnCode?: ReturnCode }
): Buffer {
    const length = payload.length + 8; // 8 bytes for header part2 (client+session+4control)
    const header = serializeHeader({
        serviceId,
        methodId,
        length,
        clientId: opts?.clientId ?? 0,
        sessionId,
        protocolVersion: opts?.protocolVersion ?? 0x01,
        interfaceVersion: opts?.interfaceVersion ?? 0x01,
        messageType,
        returnCode: opts?.returnCode ?? ReturnCode.OK,
    });
    return Buffer.concat([header, payload]);
}

// ── Primitive Serialization Helpers (Big-Endian) ──

export function serializeInt8(val: number): Buffer { const b = Buffer.alloc(1); b.writeInt8(val); return b; }
export function serializeInt16(val: number): Buffer { const b = Buffer.alloc(2); b.writeInt16BE(val); return b; }
export function serializeInt32(val: number): Buffer { const b = Buffer.alloc(4); b.writeInt32BE(val); return b; }
export function serializeInt64(val: bigint): Buffer { const b = Buffer.alloc(8); b.writeBigInt64BE(val); return b; }
export function serializeUInt8(val: number): Buffer { const b = Buffer.alloc(1); b.writeUInt8(val); return b; }
export function serializeUInt16(val: number): Buffer { const b = Buffer.alloc(2); b.writeUInt16BE(val); return b; }
export function serializeUInt32(val: number): Buffer { const b = Buffer.alloc(4); b.writeUInt32BE(val); return b; }
export function serializeUInt64(val: bigint): Buffer { const b = Buffer.alloc(8); b.writeBigUInt64BE(val); return b; }
export function serializeFloat32(val: number): Buffer { const b = Buffer.alloc(4); b.writeFloatBE(val); return b; }
export function serializeFloat64(val: number): Buffer { const b = Buffer.alloc(8); b.writeDoubleBE(val); return b; }
export function serializeBool(val: boolean): Buffer { return Buffer.from([val ? 1 : 0]); }
export function serializeString(val: string): Buffer {
    const encoded = Buffer.from(val, 'utf-8');
    const lenBuf = Buffer.alloc(4);
    lenBuf.writeUInt32BE(encoded.length);
    return Buffer.concat([lenBuf, encoded]);
}

export function serializeList(items: Buffer[]): Buffer {
    const content = Buffer.concat(items);
    const lenBuf = Buffer.alloc(4);
    lenBuf.writeUInt32BE(content.length);
    return Buffer.concat([lenBuf, content]);
}

// ── Primitive Deserialization Helpers ──

export interface DeserResult<T> { value: T; bytesRead: number; }

export function deserializeInt8(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readInt8(off), bytesRead: 1 }; }
export function deserializeInt16(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readInt16BE(off), bytesRead: 2 }; }
export function deserializeInt32(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readInt32BE(off), bytesRead: 4 }; }
export function deserializeInt64(buf: Buffer, off: number): DeserResult<bigint> { return { value: buf.readBigInt64BE(off), bytesRead: 8 }; }
export function deserializeUInt8(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readUInt8(off), bytesRead: 1 }; }
export function deserializeUInt16(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readUInt16BE(off), bytesRead: 2 }; }
export function deserializeUInt32(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readUInt32BE(off), bytesRead: 4 }; }
export function deserializeUInt64(buf: Buffer, off: number): DeserResult<bigint> { return { value: buf.readBigUInt64BE(off), bytesRead: 8 }; }
export function deserializeFloat32(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readFloatBE(off), bytesRead: 4 }; }
export function deserializeFloat64(buf: Buffer, off: number): DeserResult<number> { return { value: buf.readDoubleBE(off), bytesRead: 8 }; }
export function deserializeBool(buf: Buffer, off: number): DeserResult<boolean> { return { value: buf[off] !== 0, bytesRead: 1 }; }
export function deserializeString(buf: Buffer, off: number): DeserResult<string> {
    const len = buf.readUInt32BE(off);
    const str = buf.subarray(off + 4, off + 4 + len).toString('utf-8');
    return { value: str, bytesRead: 4 + len };
}
