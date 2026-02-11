/**
 * Cross-Decode Tests — Decode shared binary fixtures from tests/fixtures/
 * Same fixtures used by Python and Rust tests for cross-language consistency.
 */
import { describe, it, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { deserializeHeader, MessageType, ReturnCode } from '../dist/codec.js';
import { parseSdEntries, parseSdOptions, SdEntryType, SdOptionType } from '../dist/sd.js';

const fixturesDir = resolve(import.meta.dirname, '..', '..', '..', 'tests', 'fixtures');

function loadFixture(name) {
    return readFileSync(join(fixturesDir, name));
}

describe('Cross-Decode: RPC Request', () => {
    let data;
    before(() => { data = loadFixture('rpc_request.bin'); });

    it('parses header correctly', () => {
        const h = deserializeHeader(data);
        assert.notEqual(h, null);
        assert.equal(h.serviceId, 0x1001);
        assert.equal(h.methodId, 0x0001);
        assert.equal(h.length, 16);
        assert.equal(h.protocolVersion, 0x01);
        assert.equal(h.messageType, MessageType.REQUEST);
        assert.equal(h.returnCode, ReturnCode.OK);
    });

    it('decodes payload', () => {
        const payload = data.subarray(16);
        assert.equal(payload.readInt32BE(0), 5);
        assert.equal(payload.readInt32BE(4), 3);
    });
});

describe('Cross-Decode: RPC Response', () => {
    let data;
    before(() => { data = loadFixture('rpc_response.bin'); });

    it('parses header correctly', () => {
        const h = deserializeHeader(data);
        assert.equal(h.messageType, MessageType.RESPONSE);
        assert.equal(h.returnCode, ReturnCode.OK);
    });

    it('decodes payload', () => {
        assert.equal(data.subarray(16).readInt32BE(0), 8);
    });
});

describe('Cross-Decode: SD Offer v4', () => {
    let data;
    before(() => { data = loadFixture('sd_offer_v4.bin'); });

    it('parses SD header', () => {
        const h = deserializeHeader(data);
        assert.equal(h.serviceId, 0xFFFF);
        assert.equal(h.methodId, 0x8100);
        assert.equal(h.messageType, 0x02);
    });

    it('parses entries', () => {
        const sd = data.subarray(16);
        const entries = parseSdEntries(sd, 4);
        assert.equal(entries.length, 1);
        assert.equal(entries[0].type, SdEntryType.OFFER_SERVICE);
        assert.equal(entries[0].serviceId, 0x1234);
        assert.equal(entries[0].ttl, 0xFFFFFF);
    });

    it('[PRS_SOMEIPSD_00280] IPv4 option length is 10', () => {
        const sd = data.subarray(16);
        const options = parseSdOptions(sd, 4 + 4 + 16);
        assert.equal(options.length, 1);
        assert.equal(options[0].length, 10);
        assert.equal(options[0].type, SdOptionType.IPV4_ENDPOINT);
        assert.equal(options[0].port, 30500);
    });
});

describe('Cross-Decode: SD Offer v6', () => {
    let data;
    before(() => { data = loadFixture('sd_offer_v6.bin'); });

    it('[PRS_SOMEIPSD_00280] IPv6 option length is 22', () => {
        const sd = data.subarray(16);
        const options = parseSdOptions(sd, 4 + 4 + 16);
        assert.equal(options.length, 1);
        assert.equal(options[0].length, 22);
        assert.equal(options[0].type, SdOptionType.IPV6_ENDPOINT);
    });
});

describe('Cross-Decode: Malformed Packets', () => {
    it('truncated packet returns null', () => {
        const data = loadFixture('malformed_short.bin');
        assert.equal(deserializeHeader(data), null);
    });

    it('incorrect length still parses header', () => {
        const data = loadFixture('malformed_length.bin');
        const h = deserializeHeader(data);
        assert.notEqual(h, null);
        assert.equal(h.length, 1000);
        assert.ok(data.length - 16 < 1000, 'Actual payload shorter than claimed');
    });

    it('notification with wrong return code is detectable', () => {
        const data = loadFixture('malformed_notification.bin');
        const h = deserializeHeader(data);
        assert.equal(h.messageType, MessageType.NOTIFICATION);
        assert.notEqual(h.returnCode, ReturnCode.OK);
    });
});
