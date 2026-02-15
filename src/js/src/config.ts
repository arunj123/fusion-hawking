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
    interfaces?: string[];
    cycleOfferMs?: number;
    offerOn?: Record<string, string>;
    findOn?: string[];
}

/** SD-specific configuration. */
export interface SdConfig {
    multicastEndpoint: string;
    multicastEndpointV6?: string;
    initialDelay: number;
    offerInterval: number;
    requestTimeout: number;
}

export interface InterfaceSdConfig {
    endpoint: string;
    endpointV6?: string;
}

export interface InterfaceConfig {
    name: string;
    endpoints: Record<string, EndpointConfig>;
    sd: InterfaceSdConfig;
}

/** Top-level application configuration. */
export interface AppConfig {
    sd: SdConfig;
    providing: Record<string, ServiceConfigEntry>;
    required: Record<string, ServiceConfigEntry>;
    endpoints: Record<string, EndpointConfig>;
    interfaces: Record<string, InterfaceConfig>;
    ip: string;
    ipV6?: string;
    instanceEndpoint?: string;
    unicastBind?: Record<string, string>;
    activeInterfaceAliases?: string[];
}

/**
 * Load configuration from a JSON file.
 * Returns a normalized AppConfig.
 */
export function loadConfig(path: string, instanceName?: string): AppConfig {
    const raw = JSON.parse(readFileSync(path, 'utf-8'));
    const endpoints: Record<string, EndpointConfig> = {};

    const parseEndpointsRecursive = (section: any): Record<string, EndpointConfig> => {
        const res: Record<string, EndpointConfig> = {};
        if (!section) return res;
        for (const [name, ep] of Object.entries(section)) {
            const e = ep as any;
            res[name] = {
                ip: e.ip,
                port: e.port ?? 0,
                version: e.version ?? 4,
                interface: e.interface,
                protocol: e.protocol ?? 'udp'
            } as any;
        }
        return res;
    };

    if (raw.endpoints) {
        Object.assign(endpoints, parseEndpointsRecursive(raw.endpoints));
    }

    const parseInterfaces = (section: any): Record<string, InterfaceConfig> => {
        const res: Record<string, InterfaceConfig> = {};
        if (!section) return res;
        for (const [key, val] of Object.entries(section)) {
            const v = val as any;
            res[key] = {
                name: v.name ?? key,
                endpoints: parseEndpointsRecursive(v.endpoints),
                sd: {
                    endpoint: v.sd?.endpoint ?? v.sd?.endpoint_v4 ?? '',
                    endpointV6: v.sd?.endpoint_v6 ?? '',
                }
            };
        }
        return res;
    };

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
                interfaces: s.interfaces,
                cycleOfferMs: s.cycle_offer_ms,
                offerOn: s.offer_on,
                findOn: s.find_on,
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
        console.log(`[Config] Loading instance '${instanceName}'. Interfaces in instance config:`, inst.interfaces);
        configSource = {
            ...inst,
            endpoints: { ...raw.endpoints, ...inst.endpoints },
            ip: inst.ip ?? raw.ip,
            ip_v6: inst.ip_v6 ?? raw.ip_v6,
            unicast_bind: inst.unicast_bind,
        };
    }

    const sdRaw = configSource.sd ?? {};
    if (Object.keys(sdRaw).length === 0) {
        console.warn("[Config] Warning: 'sd' section is empty. Service Discovery settings (multicast, offer interval) may be missing.");
    }

    return {
        sd: {
            multicastEndpoint: sdRaw.multicast_endpoint ?? sdRaw.multicastEndpoint,
            multicastEndpointV6: sdRaw.multicast_endpoint_v6 ?? sdRaw.multicastEndpointV6,
            initialDelay: sdRaw.initial_delay ?? 100,
            offerInterval: sdRaw.offer_interval ?? sdRaw.cycle_offer_ms ?? 2000,
            requestTimeout: sdRaw.request_timeout_ms ?? 3000,
        },
        providing: parseServices(configSource.providing),
        required: parseServices(configSource.required == null ? configSource.requiring : configSource.required),
        endpoints,
        interfaces: parseInterfaces(raw.interfaces),
        activeInterfaceAliases: Array.isArray(configSource.interfaces) ? configSource.interfaces : undefined,
        ip: configSource.ip,
        ipV6: configSource.ip_v6,
        instanceEndpoint: configSource.endpoint,
        unicastBind: configSource.unicast_bind,
    };
}
