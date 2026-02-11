/**
 * Fusion Hawking JSON Config Loader
 *
 * Loads config.json files matching the format used by Python and C++ runtimes.
 * Configuration-driven service definitions per AUTOSAR R22-11.
 * @module
 */

import { readFileSync } from 'node:fs';

/** Network endpoint configuration. */
export interface EndpointConfig {
    ip: string;
    port: number;
    version: 4 | 6;
    interface?: string;
}

/** Service configuration within providing/required sections. */
export interface ServiceConfigEntry {
    serviceId: number;
    instanceId: number;
    endpoint: string;
    majorVersion: number;
    minorVersion: number;
    protocol: string;
    eventgroups?: number[];
    multicastEndpoint?: string;
}

/** SD-specific configuration. */
export interface SdConfig {
    multicastEndpoint: string;
    multicastEndpointV6?: string;
    initialDelay: number;
    offerInterval: number;
    requestTimeout: number;
}

/** Top-level application configuration. */
export interface AppConfig {
    sd: SdConfig;
    providing: Record<string, ServiceConfigEntry>;
    required: Record<string, ServiceConfigEntry>;
    endpoints: Record<string, EndpointConfig>;
    ip: string;
    ipV6?: string;
}

/**
 * Load configuration from a JSON file.
 * Returns a normalized AppConfig.
 */
export function loadConfig(path: string, instanceName?: string): AppConfig {
    const raw = JSON.parse(readFileSync(path, 'utf-8'));
    const endpoints: Record<string, EndpointConfig> = {};

    if (raw.endpoints) {
        for (const [name, ep] of Object.entries(raw.endpoints)) {
            const e = ep as any;
            endpoints[name] = {
                ip: e.ip ?? '127.0.0.1',
                port: e.port ?? 0,
                version: e.version ?? 4,
                interface: e.interface,
            };
        }
    }

    const parseServices = (section: any): Record<string, ServiceConfigEntry> => {
        const result: Record<string, ServiceConfigEntry> = {};
        if (!section) return result;
        for (const [name, svc] of Object.entries(section)) {
            const s = svc as any;
            result[name] = {
                serviceId: s.service_id ?? 0,
                instanceId: s.instance_id ?? 1,
                endpoint: s.endpoint ?? '',
                majorVersion: s.major_version ?? 1,
                minorVersion: s.minor_version ?? 0,
                protocol: s.protocol ?? 'udp',
                eventgroups: s.eventgroups,
                multicastEndpoint: s.multicast_endpoint,
            };
        }
        return result;
    };

    // Support multi-instance configs: if 'instances' key exists and instanceName
    // is provided, extract that instance's config and merge with shared endpoints.
    let configSource = raw;
    if (raw.instances && instanceName) {
        const inst = raw.instances[instanceName];
        if (!inst) {
            throw new Error(`Instance '${instanceName}' not found in config. Available: ${Object.keys(raw.instances).join(', ')}`);
        }
        configSource = {
            ...inst,
            endpoints: raw.endpoints,
            ip: inst.ip ?? raw.ip,
            ip_v6: inst.ip_v6 ?? raw.ip_v6,
        };
    }

    const sdRaw = configSource.sd ?? {};
    return {
        sd: {
            multicastEndpoint: sdRaw.multicast_endpoint ?? sdRaw.multicastEndpoint ?? 'sd-mcast',
            multicastEndpointV6: sdRaw.multicast_endpoint_v6 ?? sdRaw.multicastEndpointV6,
            initialDelay: sdRaw.initial_delay ?? 100,
            offerInterval: sdRaw.offer_interval ?? sdRaw.cycle_offer_ms ?? 1000,
            requestTimeout: sdRaw.request_timeout_ms ?? 3000,
        },
        providing: parseServices(configSource.providing),
        required: parseServices(configSource.required),
        endpoints,
        ip: configSource.ip ?? '127.0.0.1',
        ipV6: configSource.ip_v6,
    };
}
