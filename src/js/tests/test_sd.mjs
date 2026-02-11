/**
 * SD Tests — SOME/IP Service Discovery Protocol
 * AUTOSAR R22-11 [PRS_SOMEIPSD].
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    SdEntryType, SdOptionType,
    SD_SERVICE_ID, SD_METHOD_ID,
    IPV4_OPTION_LENGTH, IPV6_OPTION_LENGTH,
    parseSdEntries, parseSdOptions,
    buildSdOffer, buildSdSubscribe,
} from '../dist/sd.js';
import { SessionIdManager, deserializeHeader, MessageType } from '../dist/codec.js';

describe('SD Constants', () => {
    it('[PRS_SOMEIPSD_00016] SD service_id is 0xFFFF', () => {
        assert.equal(SD_SERVICE_ID, 0xFFFF);
    });

    it('[PRS_SOMEIPSD_00016] SD method_id is 0x8100', () => {
        assert.equal(SD_METHOD_ID, 0x8100);
    });

    it('[PRS_SOMEIPSD_00280] IPv4 option length is 10', () => {
        assert.equal(IPV4_OPTION_LENGTH, 10);
    });

    it('[PRS_SOMEIPSD_00280] IPv6 option length is 22', () => {
        assert.equal(IPV6_OPTION_LENGTH, 22);
    });

    it('entry types match spec', () => {
        assert.equal(SdEntryType.FIND_SERVICE, 0x00);
        assert.equal(SdEntryType.OFFER_SERVICE, 0x01);
        assert.equal(SdEntryType.SUBSCRIBE_EVENTGROUP, 0x06);
        assert.equal(SdEntryType.SUBSCRIBE_EVENTGROUP_ACK, 0x07);
    });

    it('option types match spec', () => {
        assert.equal(SdOptionType.IPV4_ENDPOINT, 0x04);
        assert.equal(SdOptionType.IPV6_ENDPOINT, 0x06);
        assert.equal(SdOptionType.IPV4_MULTICAST, 0x14);
        assert.equal(SdOptionType.IPV6_MULTICAST, 0x16);
    });
});

describe('buildSdOffer', () => {
    it('builds a valid SD Offer packet', () => {
        const mgr = new SessionIdManager();
        const pkt = buildSdOffer(0x1234, 1, 1, 10, '127.0.0.1', 30500, 0x11, mgr);

        // Parse header
        const h = deserializeHeader(pkt);
        assert.notEqual(h, null);
        assert.equal(h.serviceId, 0xFFFF);
        assert.equal(h.methodId, 0x8100);
        assert.equal(h.messageType, MessageType.NOTIFICATION);
        assert.equal(h.protocolVersion, 0x01);
        assert.equal(h.sessionId, 1);

        // Parse entries from SD payload (starts at offset 16)
        const sdPayload = pkt.subarray(16);
        const entries = parseSdEntries(sdPayload, 4);
        assert.equal(entries.length, 1);
        assert.equal(entries[0].type, SdEntryType.OFFER_SERVICE);
        assert.equal(entries[0].serviceId, 0x1234);
        assert.equal(entries[0].instanceId, 1);
        assert.equal(entries[0].majorVersion, 1);
        assert.equal(entries[0].ttl, 0xFFFFFF);
        assert.equal(entries[0].minorVersion, 10);

        // Parse options
        const entriesLen = sdPayload.readUInt32BE(4);
        const optionsOffset = 4 + 4 + entriesLen;
        const options = parseSdOptions(sdPayload, optionsOffset);
        assert.equal(options.length, 1);
        assert.equal(options[0].length, IPV4_OPTION_LENGTH, '[PRS_SOMEIPSD_00280]');
        assert.equal(options[0].type, SdOptionType.IPV4_ENDPOINT);
        assert.equal(options[0].ipAddress, '127.0.0.1');
        assert.equal(options[0].port, 30500);
        assert.equal(options[0].protocol, 0x11); // UDP
    });

    it('increments session IDs for subsequent offers', () => {
        const mgr = new SessionIdManager();
        const pkt1 = buildSdOffer(0x1234, 1, 1, 10, '127.0.0.1', 30500, 0x11, mgr);
        const pkt2 = buildSdOffer(0x1234, 1, 1, 10, '127.0.0.1', 30500, 0x11, mgr);
        const h1 = deserializeHeader(pkt1);
        const h2 = deserializeHeader(pkt2);
        assert.equal(h1.sessionId, 1);
        assert.equal(h2.sessionId, 2);
    });
});

describe('buildSdSubscribe', () => {
    it('builds a valid Subscribe packet', () => {
        const mgr = new SessionIdManager();
        const pkt = buildSdSubscribe(0x1234, 1, 1, 1, mgr);
        const h = deserializeHeader(pkt);
        assert.equal(h.serviceId, 0xFFFF);
        assert.equal(h.methodId, 0x8100);

        const sdPayload = pkt.subarray(16);
        const entries = parseSdEntries(sdPayload, 4);
        assert.equal(entries.length, 1);
        assert.equal(entries[0].type, SdEntryType.SUBSCRIBE_EVENTGROUP);
        assert.equal(entries[0].serviceId, 0x1234);
    });
});

describe('Golden SD Hex References', () => {
    it('parses golden v4 offer', () => {
        const golden = Buffer.from(
            'ffff8100' + '0000002c' + '00000001' + '01010200' +
            '80000000' + '00000010' +
            '01000010' + '12340001' + '01ffffff' + '0000000a' +
            '0000000c' +
            '000a0400' + '7f000001' + '00117724', 'hex');

        const h = deserializeHeader(golden);
        assert.equal(h.serviceId, 0xFFFF);
        assert.equal(h.methodId, 0x8100);

        const sd = golden.subarray(16);
        const entries = parseSdEntries(sd, 4);
        assert.equal(entries[0].type, SdEntryType.OFFER_SERVICE);
        assert.equal(entries[0].serviceId, 0x1234);

        const options = parseSdOptions(sd, 4 + 4 + 16);
        assert.equal(options[0].length, 10);
        assert.equal(options[0].type, SdOptionType.IPV4_ENDPOINT);
        assert.equal(options[0].port, 30500);
    });

    it('parses golden v6 option bytes', () => {
        // Standalone IPv6 option
        const optBuf = Buffer.from(
            '00000018' +  // options array length = 24
            '00160600' +  // len=22, type=IPv6 endpoint
            '00000000000000000000000000000001' + // ::1
            '00117724', 'hex');

        const options = parseSdOptions(optBuf, 0);
        assert.equal(options.length, 1);
        assert.equal(options[0].length, 22, '[PRS_SOMEIPSD_00280] IPv6 len=22');
        assert.equal(options[0].type, SdOptionType.IPV6_ENDPOINT);
        assert.equal(options[0].port, 30500);
    });
});
