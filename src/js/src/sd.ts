/**
 * Fusion Hawking SOME/IP-SD — Service Discovery Protocol
 *
 * Implements AUTOSAR R22-11 [PRS_SOMEIPSD] entry and option
 * parsing/building for OfferService, FindService, Subscribe, and
 * SubscribeAck.
 * @module
 */

import { HEADER_SIZE, SessionIdManager, MessageType, ReturnCode, serializeHeader } from './codec.js';

/** SD Entry Types. */
export enum SdEntryType {
    FIND_SERVICE = 0x00,
    OFFER_SERVICE = 0x01,
    SUBSCRIBE_EVENTGROUP = 0x06,
    SUBSCRIBE_EVENTGROUP_ACK = 0x07,
}

/** SD Option Types. */
export enum SdOptionType {
    IPV4_ENDPOINT = 0x04,
    IPV6_ENDPOINT = 0x06,
    IPV4_MULTICAST = 0x14,
    IPV6_MULTICAST = 0x16,
}

/** SD Protocol Constants [PRS_SOMEIPSD_00016]. */
export const SD_SERVICE_ID = 0xFFFF;
export const SD_METHOD_ID = 0x8100;
export const SD_FLAGS_REBOOT = 0x80;

/** IPv4 endpoint option field length [PRS_SOMEIPSD_00280]. */
export const IPV4_OPTION_LENGTH = 10;
/** IPv6 endpoint option field length [PRS_SOMEIPSD_00280]. */
export const IPV6_OPTION_LENGTH = 22;

/** Parsed SD Entry. */
export interface SdEntry {
    type: SdEntryType;
    index1st: number;
    index2nd: number;
    numOpts1: number;
    numOpts2: number;
    serviceId: number;
    instanceId: number;
    majorVersion: number;
    ttl: number;
    minorVersion: number;
}

/** Parsed SD Option. */
export interface SdOption {
    length: number;
    type: SdOptionType;
    ipAddress: string;
    protocol: number;
    port: number;
}

/** Parse SD entries from a buffer starting at `offset`. */
export function parseSdEntries(buf: Buffer, offset: number): SdEntry[] {
    if (offset + 4 > buf.length) return [];
    const entriesLen = buf.readUInt32BE(offset);
    const entries: SdEntry[] = [];
    let pos = offset + 4;
    const end = pos + entriesLen;
    while (pos + 16 <= end) {
        const optsByte = buf[pos + 3];
        const majTtl = buf.readUInt32BE(pos + 8);
        entries.push({
            type: buf[pos] as SdEntryType,
            index1st: buf[pos + 1],
            index2nd: buf[pos + 2],
            numOpts1: (optsByte >> 4) & 0x0F,
            numOpts2: optsByte & 0x0F,
            serviceId: buf.readUInt16BE(pos + 4),
            instanceId: buf.readUInt16BE(pos + 6),
            majorVersion: (majTtl >> 24) & 0xFF,
            ttl: majTtl & 0x00FFFFFF,
            minorVersion: buf.readUInt32BE(pos + 12),
        });
        pos += 16;
    }
    return entries;
}

/** Parse SD options from a buffer starting at `offset`. */
export function parseSdOptions(buf: Buffer, offset: number): SdOption[] {
    if (offset + 4 > buf.length) return [];
    const optsLen = buf.readUInt32BE(offset);
    const options: SdOption[] = [];
    let pos = offset + 4;
    const end = pos + optsLen;
    while (pos + 4 <= end) {
        const optLen = buf.readUInt16BE(pos);
        const optType = buf[pos + 2] as SdOptionType;
        let ipAddress = '';
        let protocol = 0;
        let port = 0;

        if (optType === SdOptionType.IPV4_ENDPOINT || optType === SdOptionType.IPV4_MULTICAST) {
            // [Len:2][Type:1][Res:1][IPv4:4][Res:1][Proto:1][Port:2]
            if (pos + 12 <= end) {
                const a = buf[pos + 4], b = buf[pos + 5], c = buf[pos + 6], d = buf[pos + 7];
                ipAddress = `${a}.${b}.${c}.${d}`;
                protocol = buf[pos + 9];
                port = buf.readUInt16BE(pos + 10);
            }
        } else if (optType === SdOptionType.IPV6_ENDPOINT || optType === SdOptionType.IPV6_MULTICAST) {
            // [Len:2][Type:1][Res:1][IPv6:16][Res:1][Proto:1][Port:2]
            if (pos + 24 <= end) {
                const groups: string[] = [];
                for (let i = 0; i < 8; i++) {
                    groups.push(buf.readUInt16BE(pos + 4 + i * 2).toString(16));
                }
                ipAddress = groups.join(':');
                protocol = buf[pos + 21];
                port = buf.readUInt16BE(pos + 22);
            }
        }

        options.push({ length: optLen, type: optType, ipAddress, protocol, port });
        pos += 2 + optLen;
    }
    return options;
}

/**
 * Build a complete SD Offer packet.
 * @param serviceId Service to offer
 * @param instanceId Instance ID
 * @param majorVersion Major version
 * @param minorVersion Minor version
 * @param ipAddress IPv4 address string (e.g. "127.0.0.1")
 * @param port Service port
 * @param protocol 0x11=UDP, 0x06=TCP
 * @param sessionMgr SessionIdManager for tracking
 */
export function buildSdOffer(
    serviceId: number,
    instanceId: number,
    majorVersion: number,
    minorVersion: number,
    ipAddress: string,
    port: number,
    protocol: number = 0x11,
    sessionMgr?: SessionIdManager,
): Buffer {
    // SD Payload
    const sdPayload = Buffer.alloc(4 + 4 + 16 + 4 + 12);
    let off = 0;

    // Flags: reboot=1
    sdPayload.writeUInt32BE(0x80000000, off); off += 4;
    // Entries length
    sdPayload.writeUInt32BE(16, off); off += 4;
    // Entry
    sdPayload[off++] = SdEntryType.OFFER_SERVICE;
    sdPayload[off++] = 0; // index1st
    sdPayload[off++] = 0; // index2nd
    sdPayload[off++] = 0x10; // #opt1=1, #opt2=0
    sdPayload.writeUInt16BE(serviceId, off); off += 2;
    sdPayload.writeUInt16BE(instanceId, off); off += 2;
    const majTtl = ((majorVersion & 0xFF) << 24) | 0xFFFFFF;
    sdPayload.writeUInt32BE(majTtl >>> 0, off); off += 4;
    sdPayload.writeUInt32BE(minorVersion, off); off += 4;
    // Options length
    sdPayload.writeUInt32BE(12, off); off += 4;
    // IPv4 Endpoint Option
    sdPayload.writeUInt16BE(IPV4_OPTION_LENGTH, off); off += 2;
    sdPayload[off++] = SdOptionType.IPV4_ENDPOINT;
    sdPayload[off++] = 0; // reserved
    const parts = ipAddress.split('.').map(Number);
    for (const p of parts) sdPayload[off++] = p;
    sdPayload[off++] = 0; // reserved
    sdPayload[off++] = protocol;
    sdPayload.writeUInt16BE(port, off); off += 2;

    // SOME/IP Header
    const sessionId = sessionMgr?.nextSessionId(SD_SERVICE_ID, SD_METHOD_ID) ?? 1;
    const header = serializeHeader({
        serviceId: SD_SERVICE_ID,
        methodId: SD_METHOD_ID,
        length: sdPayload.length + 8,
        clientId: 0,
        sessionId,
        protocolVersion: 0x01,
        interfaceVersion: 0x01,
        messageType: MessageType.NOTIFICATION,
        returnCode: ReturnCode.OK,
    });

    return Buffer.concat([header, sdPayload]);
}

/**
 * Build a SubscribeEventgroup SD packet.
 */
export function buildSdSubscribe(
    serviceId: number,
    instanceId: number,
    majorVersion: number,
    eventgroupId: number,
    sessionMgr?: SessionIdManager,
): Buffer {
    const sdPayload = Buffer.alloc(4 + 4 + 16 + 4);
    let off = 0;

    sdPayload.writeUInt32BE(0x80000000, off); off += 4;
    sdPayload.writeUInt32BE(16, off); off += 4;
    sdPayload[off++] = SdEntryType.SUBSCRIBE_EVENTGROUP;
    sdPayload[off++] = 0;
    sdPayload[off++] = 0;
    sdPayload[off++] = 0x00; // no options
    sdPayload.writeUInt16BE(serviceId, off); off += 2;
    sdPayload.writeUInt16BE(instanceId, off); off += 2;
    const majTtl = ((majorVersion & 0xFF) << 24) | 0xFFFFFF;
    sdPayload.writeUInt32BE(majTtl >>> 0, off); off += 4;
    // Reserved (12 bits) + Eventgroup ID (16 bits) in the 4-byte minor field
    sdPayload.writeUInt32BE(eventgroupId & 0xFFFF, off); off += 4;
    // Options length = 0
    sdPayload.writeUInt32BE(0, off); off += 4;

    const sessionId = sessionMgr?.nextSessionId(SD_SERVICE_ID, SD_METHOD_ID) ?? 1;
    const header = serializeHeader({
        serviceId: SD_SERVICE_ID,
        methodId: SD_METHOD_ID,
        length: sdPayload.length + 8,
        clientId: 0,
        sessionId,
        protocolVersion: 0x01,
        interfaceVersion: 0x01,
        messageType: MessageType.NOTIFICATION,
        returnCode: ReturnCode.OK,
    });

    return Buffer.concat([header, sdPayload]);
}
