/**
 * Config Tests — JSON configuration loading and validation.
 */
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, unlinkSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { loadConfig } from '../dist/config.js';

const tmpDir = join(import.meta.dirname, '..', 'tests', '.tmp');
const configPath = join(tmpDir, 'test_config.json');

describe('Config Loader', () => {
    before(() => {
        mkdirSync(tmpDir, { recursive: true });
        writeFileSync(configPath, JSON.stringify({
            ip: '192.168.1.100',
            ip_v6: 'fd00::1',
            sd: {
                multicast_endpoint: 'sd-mcast',
                multicast_endpoint_v6: 'sd-mcast-v6',
                initial_delay: 200,
                offer_interval: 2000,
                request_timeout_ms: 5000,
            },
            endpoints: {
                'sd-mcast': { ip: '224.0.0.1', port: 30490, version: 4, interface: 'eth0' },
                'sd-mcast-v6': { ip: 'ff02::1', port: 30490, version: 6 },
                'ep-main': { ip: '192.168.1.100', port: 30500, version: 4 },
            },
            providing: {
                math_service: {
                    service_id: 4097,
                    instance_id: 1,
                    endpoint: 'ep-main',
                    major_version: 1,
                    minor_version: 10,
                    protocol: 'udp',
                    eventgroups: [1],
                },
            },
            required: {
                sort_service: {
                    service_id: 4098,
                    instance_id: 1,
                    endpoint: 'ep-main',
                    major_version: 1,
                    minor_version: 0,
                    protocol: 'udp',
                },
            },
        }));
    });

    after(() => {
        try { unlinkSync(configPath); } catch { /* ignore */ }
    });

    it('loads and normalizes config', () => {
        const cfg = loadConfig(configPath);
        assert.equal(cfg.ip, '192.168.1.100');
        assert.equal(cfg.ipV6, 'fd00::1');
        assert.equal(cfg.sd.multicastEndpoint, 'sd-mcast');
        assert.equal(cfg.sd.initialDelay, 200);
        assert.equal(cfg.sd.offerInterval, 2000);
        assert.equal(cfg.sd.requestTimeout, 5000);
    });

    it('parses endpoints', () => {
        const cfg = loadConfig(configPath);
        assert.equal(Object.keys(cfg.endpoints).length, 3);
        assert.equal(cfg.endpoints['sd-mcast'].ip, '224.0.0.1');
        assert.equal(cfg.endpoints['sd-mcast'].port, 30490);
        assert.equal(cfg.endpoints['sd-mcast'].version, 4);
    });

    it('parses providing services', () => {
        const cfg = loadConfig(configPath);
        const math = cfg.providing['math_service'];
        assert.notEqual(math, undefined);
        assert.equal(math.serviceId, 4097);
        assert.equal(math.instanceId, 1);
        assert.equal(math.majorVersion, 1);
        assert.equal(math.minorVersion, 10);
        assert.equal(math.protocol, 'udp');
        assert.deepEqual(math.eventgroups, [1]);
    });

    it('parses required services', () => {
        const cfg = loadConfig(configPath);
        const sort = cfg.required['sort_service'];
        assert.notEqual(sort, undefined);
        assert.equal(sort.serviceId, 4098);
    });
});
