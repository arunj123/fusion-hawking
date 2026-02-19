/**
 * Fusion Hawking SOME/IP Runtime — JavaScript/TypeScript
 *
 * Main runtime class providing:
 *  - Service offering via SOME/IP-SD
 *  - Request/Response RPC
 *  - Event notifications
 *  - Request handler registration
 *
 * Follows the same API and behavior as Python and C++ runtimes.
 * Based on AUTOSAR R22-11.
 * @module
 */

import * as os from 'node:os';
import {
    HEADER_SIZE,
    MessageType,
    ReturnCode,
    SessionIdManager,
    deserializeHeader,
    buildPacket,
    serializeHeader,
    type SomeIpHeader,
} from './codec.js';
import {
    SD_SERVICE_ID,
    SD_METHOD_ID,
    buildSdOffer,
    buildSdSubscribe,
    parseSdEntries,
    parseSdOptions,
    SdEntryType,
    SdOptionType,
} from './sd.js';
import { TpHeader, TpReassembler, segmentPayload } from './tp.js';
import { UdpTransport, TcpTransport, TcpServerTransport, type ITransport, type RemoteInfo } from './transport.js';
import { type ILogger, LogLevel, ConsoleLogger } from './logger.js';
import { type AppConfig, loadConfig, type InterfaceConfig } from './config.js';

/** Handler function for incoming requests. */
export type RequestHandler = (
    header: SomeIpHeader,
    payload: Buffer,
) => Buffer | null;

/** Response from a request. */
export interface SomeIpResponse {
    returnCode: ReturnCode;
    payload: Buffer;
}

/** Pending request waiting for a response. */
interface PendingRequest {
    resolve: (response: SomeIpResponse) => void;
    reject: (err: Error) => void;
    timer: ReturnType<typeof setTimeout>;
}

/** Remote service discovered via SD. */
interface RemoteService {
    address: string;
    port: number;
    protocol: number;
    majorVersion: number;
    minorVersion: number;
}

/** Event subscriber info. */
interface Subscriber {
    address: string;
    port: number;
}

/** Interface-specific network state. */
interface InterfaceContext {
    alias: string;
    transport: ITransport;
    transportV6?: ITransport;
    sdTransport: ITransport;
    sdTransportV6?: ITransport;
    tcpTransport?: TcpServerTransport;
    tcpTransportV6?: TcpServerTransport;
    ip: string;
    ipV6?: string;
    ifIndex?: number;
}

export class SomeIpRuntime {
    private interfaces = new Map<string, InterfaceContext>();
    private tcpClients = new Map<string, any>(); // Placeholder for future TCP
    private sessionMgr = new SessionIdManager();
    private logger: ILogger;
    private config: AppConfig | null = null;
    private packetDump: boolean = false;

    private tpReassembler = new TpReassembler();

    public getLogger(): ILogger {
        return this.logger;
    }

    // Service management
    private handlers = new Map<number, RequestHandler>(); // methodId → handler
    private remoteServices = new Map<string, RemoteService>(); // "serviceId:instanceId" → remote
    private pendingRequests = new Map<string, PendingRequest>(); // "sessionId" → pending
    private subscribers = new Map<string, Subscriber[]>(); // "serviceId:eventgroupId" → subscribers

    // Maps endpoint names to their actual bound ports (resolves ephemeral port 0)
    private boundPorts = new Map<string, number>();

    // SD timers
    private offerTimer: ReturnType<typeof setInterval> | null = null;
    private running = false;

    constructor(configPath?: string, instanceName?: string, logger?: ILogger) {
        this.logger = logger ?? new ConsoleLogger();
        this.packetDump = process.env.FUSION_PACKET_DUMP === "1" || process.env.FUSION_PACKET_DUMP === "true";
        if (configPath) {
            try {
                this.config = loadConfig(configPath, instanceName);
                this.logger.log(LogLevel.INFO, 'Runtime', `Config loaded from ${configPath}${instanceName ? ` (instance: ${instanceName})` : ''}`);
            } catch (err: any) {
                this.logger.log(LogLevel.ERROR, 'Runtime', `Failed to load config: ${err.message}`);
            }
        }
    }

    private _resolveInterfaceIp(ifaceName: string, family: 4 | 6): string | undefined {
        const interfaces = os.networkInterfaces();
        let iface = interfaces[ifaceName];

        // Windows/Platform mapping: if 'lo' is requested but doesn't exist, try common aliases or search for any loopback
        if (!iface && ifaceName === 'lo') {
            iface = interfaces['Loopback Pseudo-Interface 1'] || interfaces['lo0'] || interfaces['localhost'] || interfaces['lo'];

            if (!iface) {
                // Fallback: search all interfaces for one marked as internal/loopback
                for (const name in interfaces) {
                    const candidate = interfaces[name];
                    if (candidate && candidate.some(a => a.internal || name.toLowerCase().includes('loopback'))) {
                        iface = candidate;
                        break;
                    }
                }
            }
        }

        if (iface) {
            const addr = iface.find(a => a.family === (family === 4 ? 'IPv4' : 'IPv6') || (a.family as any) === (family === 4 ? 4 : 6));
            if (addr) return addr.address;
        }

        return undefined;
    }

    private _dumpPacket(data: Buffer, rinfo: { address: string; port: number }) {
        if (!this.packetDump) return;
        if (data.length < 16) return;
        const sid = data.readUInt16BE(0);
        const mid = data.readUInt16BE(2);
        const length = data.readUInt32BE(4);
        const cid = data.readUInt16BE(8);
        const ssid = data.readUInt16BE(10);
        const pv = data[12];
        const iv = data[13];
        const mt = data[14];
        const rc = data[15];

        const mtMap: Record<number, string> = { 0: "REQ", 1: "REQ_NO_RET", 2: "NOTIF", 0x80: "RESP", 0x81: "ERR" };
        const mtStr = mtMap[mt] || `0x${mt.toString(16)}`;

        this.logger.log(LogLevel.DEBUG, "DUMP", `\n[DUMP] --- SOME/IP Message from ${rinfo.address}:${rinfo.port} ---`);
        this.logger.log(LogLevel.DEBUG, "DUMP", `  [Header] Service:0x${sid.toString(16).padStart(4, '0')} Method:0x${mid.toString(16).padStart(4, '0')} Len:${length} Client:0x${cid.toString(16).padStart(4, '0')} Session:0x${ssid.toString(16).padStart(4, '0')}`);
        this.logger.log(LogLevel.DEBUG, "DUMP", `  [Header] Proto:v${pv} Iface:v${iv} Type:${mtStr} Return:0x${rc.toString(16).padStart(2, '0')}`);

        if (sid === 0xFFFF && mid === 0x8100) {
            const payload = data.subarray(HEADER_SIZE);
            if (payload.length >= 8) {
                const entries = parseSdEntries(payload, 4);
                for (const entry of entries) {
                    const typeName = { [SdEntryType.FIND_SERVICE]: "FindService", [SdEntryType.OFFER_SERVICE]: "OfferService", [SdEntryType.SUBSCRIBE_EVENTGROUP]: "Subscribe", [SdEntryType.SUBSCRIBE_EVENTGROUP_ACK]: "SubAck" }[entry.type] || `0x${entry.type.toString(16)}`;
                    this.logger.log(LogLevel.DEBUG, "DUMP", `  [Entry] ${typeName}: Service=0x${entry.serviceId.toString(16).padStart(4, '0')} Inst=0x${entry.instanceId.toString(16).padStart(4, '0')} TTL=${entry.ttl}`);
                }
                const entriesLen = payload.readUInt32BE(4);
                const options = parseSdOptions(payload, 4 + 4 + entriesLen);
                for (const opt of options) {
                    const typeName = { [SdOptionType.IPV4_ENDPOINT]: "IPv4 Endpt", [SdOptionType.IPV6_ENDPOINT]: "IPv6 Endpt", [SdOptionType.IPV4_MULTICAST]: "IPv4 Multicast", [SdOptionType.IPV6_MULTICAST]: "IPv6 Multicast" }[opt.type] || `0x${opt.type.toString(16)}`;
                    this.logger.log(LogLevel.DEBUG, "DUMP", `  [Option] ${typeName}: ${opt.ipAddress}:${opt.port} (${opt.protocol === 0x06 ? 'TCP' : 'UDP'})`);
                }
            }
        }
        this.logger.log(LogLevel.DEBUG, "DUMP", "--------------------------------------\n");
    }

    /** Load config from a JSON file and initialize. */
    async loadConfigFile(path: string, instanceName?: string): Promise<void> {
        this.config = loadConfig(path, instanceName);
        this.logger.log(LogLevel.INFO, 'Runtime', `Config loaded from ${path}${instanceName ? ` (instance: ${instanceName})` : ''}`);
    }

    /** Set config programmatically. */
    setConfig(config: AppConfig): void {
        this.config = config;
    }

    /** Register a request handler for a specific method ID. */
    registerHandler(methodId: number, handler: RequestHandler): void {
        this.handlers.set(methodId, handler);
        this.logger.log(LogLevel.INFO, 'Runtime', `Handler registered for method 0x${methodId.toString(16)}`);
    }

    /**
     * Start the runtime: bind transports, set up SD, start offering.
     */
    async start(bindAddress?: string, bindPort: number = 0): Promise<void> {
        this.running = true;

        if (!this.config) {
            // Minimal mode without config — bind address is mandatory
            if (!bindAddress) {
                throw new Error('No config loaded and no bindAddress provided. Cannot start: bind address must be explicitly specified.');
            }
            const ip = bindAddress;
            const transport = new UdpTransport('udp4', this.logger);
            await transport.bind(ip, bindPort);
            transport.onMessage((data: Buffer, rinfo: RemoteInfo) => this.handleMessage(data, rinfo, undefined));
            this.interfaces.set("default", { alias: "default", transport, sdTransport: transport, ip });
            this.logger.log(LogLevel.INFO, 'Runtime', `Started (minimal) on ${ip}:${bindPort}`);
        } else {
            // Load from interfaces map
            const aliasesToBind = this.config.activeInterfaceAliases ?? Object.keys(this.config.interfaces);
            this.logger.log(LogLevel.INFO, 'Runtime', `Binding interfaces: ${aliasesToBind.join(', ')}`);
            for (const alias of aliasesToBind) {
                const ifaceCfg: InterfaceConfig = this.config!.interfaces[alias];
                if (!ifaceCfg) {
                    this.logger.log(LogLevel.WARN, 'Runtime', `Interface alias '${alias}' found in active list but not in config interfaces.`);
                    continue;
                }
                const ifaceName = ifaceCfg.name ?? alias;
                // We typically bind to the SD endpoint's IP or the first endpoint's IP
                const sdEpKey = ifaceCfg.sd?.endpoint;
                const sdEp = ifaceCfg.endpoints[sdEpKey];

                // Determine bind IPs
                let bindIpV4: string | undefined;
                let bindIpV6: string | undefined;

                // 1. Check unicastBind
                if (this.config.unicastBind && this.config.unicastBind[alias]) {
                    const bindEpName = this.config.unicastBind[alias];
                    if (this.config.endpoints[bindEpName]) {
                        const ep = this.config.endpoints[bindEpName];
                        if (ep.version === 4) bindIpV4 = ep.ip;
                        else if (ep.version === 6) bindIpV6 = ep.ip;
                    } else if (ifaceCfg.endpoints[bindEpName]) {
                        const ep = ifaceCfg.endpoints[bindEpName];
                        if (ep.version === 4) bindIpV4 = ep.ip;
                        else if (ep.version === 6) bindIpV6 = ep.ip;
                    }
                }

                // 3. Fallback: Try to find IPs from any endpoint on this interface
                if (!bindIpV4 || !bindIpV6) {
                    for (const ep of Object.values(ifaceCfg.endpoints)) {
                        const resolved = this._resolveInterfaceIp(ifaceName, ep.version);
                        if (ep.version === 4 && !bindIpV4) bindIpV4 = resolved ?? ep.ip;
                        if (ep.version === 6 && !bindIpV6) bindIpV6 = resolved ?? ep.ip;
                    }
                }

                if (!bindIpV4 && !bindIpV6) {
                    this.logger.log(LogLevel.WARN, 'Runtime', `No IPs resolved for interface ${alias} (${ifaceName})`);
                    continue;
                }

                const ctx: InterfaceContext = { alias, ip: bindIpV4 ?? '', ipV6: bindIpV6 ?? '', transport: null as any, sdTransport: null as any };

                if (bindIpV4) {
                    const mainBindTarget = bindIpV4;
                    const mainTransport = new UdpTransport('udp4', this.logger);
                    await mainTransport.bind(mainBindTarget, bindPort);
                    mainTransport.onMessage((data: Buffer, rinfo: RemoteInfo) => this.handleMessage(data, rinfo, ctx));
                    ctx.transport = mainTransport;

                    if (sdEp && sdEp.version === 4) {
                        const sdTransport = new UdpTransport('udp4', this.logger, true);
                        const isWindows = os.platform() === 'win32';
                        const bindTarget = isWindows ? bindIpV4 : sdEp.ip;
                        await sdTransport.bind(bindTarget!, sdEp.port);
                        await sdTransport.joinMulticast(sdEp.ip, bindIpV4);
                        sdTransport.setMulticastLoopback(true);
                        sdTransport.setMulticastInterface(bindIpV4);
                        sdTransport.onMessage((data, rinfo) => this.handleMessage(data, rinfo, ctx));
                        ctx.sdTransport = sdTransport;
                    } else {
                        ctx.sdTransport = mainTransport;
                    }

                    // Check for TCP endpoints on IPv4
                    const hasTcpV4 = Object.values(ifaceCfg.endpoints).some(ep => ep.version === 4 && ep.protocol === 'tcp');
                    if (hasTcpV4) {
                        const tcpServer = new TcpServerTransport(this.logger);
                        await tcpServer.bind(bindIpV4!, bindPort);
                        tcpServer.onMessage((data, rinfo) => this.handleMessage(data, rinfo, ctx));
                        ctx.tcpTransport = tcpServer;
                    }
                }

                if (bindIpV6) {
                    const isWindows = os.platform() === 'win32';
                    const mainBindTargetV6 = isWindows ? '::' : bindIpV6;
                    const mainTransportV6 = new UdpTransport('udp6', this.logger);
                    await mainTransportV6.bind(mainBindTargetV6, bindPort);
                    mainTransportV6.onMessage((data: Buffer, rinfo: RemoteInfo) => this.handleMessage(data, rinfo, ctx));
                    ctx.transportV6 = mainTransportV6;

                    // IPv6 SD transport with multicast
                    const sdEpKeyV6 = ifaceCfg.sd?.endpointV6;
                    const sdEpV6 = sdEpKeyV6 ? ifaceCfg.endpoints[sdEpKeyV6] : undefined;
                    if (sdEpV6 && sdEpV6.version === 6) {
                        const sdTransportV6 = new UdpTransport('udp6', this.logger, true);
                        const bindTargetV6 = (os.platform() === 'linux' || os.platform() === 'win32') ? '::' : bindIpV6;
                        await sdTransportV6.bind(bindTargetV6!, sdEpV6.port);
                        await sdTransportV6.joinMulticast(sdEpV6.ip, bindIpV6);
                        sdTransportV6.setMulticastLoopback(true);
                        sdTransportV6.onMessage((data, rinfo) => this.handleMessage(data, rinfo, ctx));
                        ctx.sdTransportV6 = sdTransportV6;
                    } else {
                        ctx.sdTransportV6 = mainTransportV6;
                    }

                    // Check for TCP endpoints on IPv6
                    const hasTcpV6 = Object.values(ifaceCfg.endpoints).some(ep => ep.version === 6 && ep.protocol === 'tcp');
                    if (hasTcpV6) {
                        const tcpServerV6 = new TcpServerTransport(this.logger);
                        await tcpServerV6.bind(bindIpV6!, bindPort);
                        tcpServerV6.onMessage((data, rinfo) => this.handleMessage(data, rinfo, ctx));
                        ctx.tcpTransportV6 = tcpServerV6;
                    }
                }

                this.interfaces.set(alias, ctx);

                // Populate boundPorts for all unicast endpoints on this interface
                for (const [epName, ep] of Object.entries(ifaceCfg.endpoints)) {
                    if (ep.ip.startsWith('224.') || ep.ip.startsWith('239.') || ep.ip.toLowerCase().startsWith('ff')) continue;
                    // All endpoints on this interface share the same transport, use its actual bound port
                    const actualPort = ctx.transport.localPort ?? ep.port;
                    this.boundPorts.set(epName, actualPort);
                }

                this.logger.log(LogLevel.INFO, 'Runtime', `Initialized interface ${alias} on ${bindIpV4 || bindIpV6}`);
            }

            // Start cyclic offers
            this.startCycle();
        }
    }

    /** Stop the runtime and clean up resources. */
    stop(): void {
        this.running = false;
        if (this.offerTimer) {
            clearInterval(this.offerTimer);
            this.offerTimer = null;
        }
        for (const pending of this.pendingRequests.values()) {
            clearTimeout(pending.timer);
            pending.reject(new Error('Runtime stopped'));
        }
        this.pendingRequests.clear();
        for (const ctx of this.interfaces.values()) {
            ctx.transport.close();
            ctx.transportV6?.close();
            if (ctx.sdTransport !== ctx.transport) ctx.sdTransport.close();
            ctx.tcpTransport?.close();
            ctx.tcpTransportV6?.close();
        }
        for (const client of this.tcpClients.values()) {
            client.close();
        }
        this.tcpClients.clear();
        this.interfaces.clear();
        this.logger.log(LogLevel.INFO, 'Runtime', 'Stopped');
    }

    /**
     * Send a request and wait for a response.
     */
    async sendRequest(
        serviceId: number,
        methodId: number,
        payload: Buffer,
        targetAddress: string,
        targetPort: number,
        timeoutMs: number = 8000,
    ): Promise<SomeIpResponse> {
        const sessionId = this.sessionMgr.nextSessionId(serviceId, methodId);
        const packet = buildPacket(serviceId, methodId, sessionId, MessageType.REQUEST, payload);

        let ifAlias = "";
        if (this.config) {
            for (const client of Object.values(this.config.required)) {
                if (client.serviceId === serviceId) ifAlias = client.interfaces?.[0] || "";
            }
        }
        const ctx = this.interfaces.get(ifAlias) || this.interfaces.values().next().value;
        if (!ctx) throw new Error("No available interfaces for request");

        const isV6 = targetAddress.includes(':');

        let protocol = 'udp';
        if (this.config) {
            const req = Object.values(this.config.required).find(r => r.serviceId === serviceId);
            if (req) protocol = req.protocol?.toLowerCase() || 'udp';
        }

        if (protocol === 'tcp') {
            const clientKey = `${targetAddress}:${targetPort}`;
            let tcpClient = this.tcpClients.get(clientKey);
            if (!tcpClient) {
                tcpClient = new TcpTransport(this.logger);
                await tcpClient.connect(targetAddress, targetPort);
                tcpClient.onMessage((data: Buffer, rinfo: RemoteInfo) => this.handleMessage(data, rinfo, ctx));
                this.tcpClients.set(clientKey, tcpClient);
            }

            return new Promise<SomeIpResponse>((resolve, reject) => {
                const timer = setTimeout(() => {
                    this.pendingRequests.delete(String(sessionId));
                    reject(new Error(`TCP Request timeout for session ${sessionId}`));
                }, timeoutMs);

                this.pendingRequests.set(String(sessionId), { resolve, reject, timer });
                tcpClient.send(packet, targetAddress, targetPort).catch(reject);
            });
        } else {
            const transport = isV6 ? (ctx.transportV6 || ctx.transport) : ctx.transport;
            return new Promise<SomeIpResponse>((resolve, reject) => {
                const timer = setTimeout(() => {
                    this.pendingRequests.delete(String(sessionId));
                    reject(new Error(`Request timeout for session ${sessionId}`));
                }, timeoutMs);

                this.pendingRequests.set(String(sessionId), { resolve, reject, timer });
                transport.send(packet, targetAddress, targetPort).catch(reject);
            });
        }
    }

    /**
     * Send a fire-and-forget request.
     */
    async sendRequestNoReturn(
        serviceId: number,
        methodId: number,
        payload: Buffer,
        targetAddress: string,
        targetPort: number,
    ): Promise<void> {
        const sessionId = this.sessionMgr.nextSessionId(serviceId, methodId);
        const packet = buildPacket(serviceId, methodId, sessionId, MessageType.REQUEST_NO_RETURN, payload);
        const ctx = this.interfaces.values().next().value;
        if (!ctx) return;
        const isV6 = targetAddress.includes(':');
        const transport = isV6 ? (ctx.transportV6 || ctx.transport) : ctx.transport;
        await transport.send(packet, targetAddress, targetPort);
    }

    /**
     * Send a notification (event) to all subscribers.
     */
    async sendNotification(
        serviceId: number,
        eventId: number,
        payload: Buffer,
    ): Promise<void> {
        const offeringIfaces: InterfaceContext[] = [];
        if (this.config) {
            for (const svc of Object.values(this.config.providing)) {
                if (svc.serviceId === serviceId) {
                    for (const alias of (svc.interfaces || [])) {
                        const ctx = this.interfaces.get(alias);
                        if (ctx && !offeringIfaces.includes(ctx)) offeringIfaces.push(ctx);
                    }
                }
            }
        }
        if (offeringIfaces.length === 0) {
            const first = this.interfaces.values().next().value;
            if (first) offeringIfaces.push(first);
        }

        const sessionId = this.sessionMgr.nextSessionId(serviceId, eventId);
        const packet = buildPacket(serviceId, eventId, sessionId, MessageType.NOTIFICATION, payload);

        for (const [key, subs] of this.subscribers) {
            const [sid] = key.split(':').map(Number);
            if (sid !== serviceId) continue;

            for (const sub of subs) {
                const isV6 = sub.address.includes(':');
                for (const ctx of offeringIfaces) {
                    const transport = isV6 ? (ctx.transportV6 || ctx.transport) : ctx.transport;
                    await transport.send(packet, sub.address, sub.port);
                }
            }
        }
    }

    /**
     * Subscribe to an eventgroup.
     */
    async subscribeEventgroup(
        serviceId: number,
        instanceId: number,
        eventgroupId: number,
        ttl: number = 3
    ): Promise<void> {
        if (!this.config) return;

        let ifAlias = "";
        for (const client of Object.values(this.config.required)) {
            if (client.serviceId === serviceId) ifAlias = client.interfaces?.[0] || "";
        }
        const ctx = this.interfaces.get(ifAlias) || this.interfaces.values().next().value;
        if (!ctx) return;

        const sdEpKey = this.config.interfaces[ctx.alias]?.sd?.endpoint;
        const sdEp = this.config.interfaces[ctx.alias]?.endpoints[sdEpKey];
        if (!sdEp) return;

        const packet = buildSdSubscribe(serviceId, instanceId, 1, eventgroupId, this.sessionMgr);
        await ctx.sdTransport.send(packet, sdEp.ip, sdEp.port);
        this.logger.log(LogLevel.INFO, 'Runtime',
            `Subscribed to service 0x${serviceId.toString(16)} eventgroup 0x${eventgroupId.toString(16)} on ${ctx.alias}`);
    }

    /** Get a discovered remote service by service ID. */
    getRemoteService(serviceId: number, instanceId: number = 0xFFFF): RemoteService | undefined {
        if (instanceId === 0xFFFF) {
            for (const [key, svc] of this.remoteServices) {
                if (key.startsWith(`${serviceId}:`)) return svc;
            }
            return undefined;
        }
        return this.remoteServices.get(`${serviceId}:${instanceId}`);
    }

    /** Resolve service ID and instance ID from a required service alias in config. */
    getServiceIdAndInstanceByAlias(alias: string): { serviceId: number, instanceId: number } | undefined {
        if (!this.config) return undefined;
        const entry = this.config.required[alias];
        if (!entry) return undefined;
        return { serviceId: entry.serviceId, instanceId: entry.instanceId };
    }

    /** bound port of first interface */
    get localPort(): number { return this.interfaces.values().next().value?.transport.localPort ?? 0; }
    get localAddress(): string { return this.interfaces.values().next().value?.ip ?? ''; }

    // ── Private Methods ──

    private handleMessage(data: Buffer, rinfo: RemoteInfo, ctx?: InterfaceContext): void {
        if (this.packetDump) {
            console.log(`[Runtime] handleMessage: ${data.length} bytes from ${rinfo.address}:${rinfo.port}`);
            this._dumpPacket(data, rinfo);
        }
        const header = deserializeHeader(data);
        if (!header) return;

        if (header.serviceId === SD_SERVICE_ID && header.methodId === SD_METHOD_ID) {
            this.logger.log(LogLevel.DEBUG, 'Runtime', `[DEBUG] SD Packet from ${rinfo.address}:${rinfo.port}`);
            this.handleSdMessage(data, rinfo, ctx);
            return;
        }

        let payload = data.subarray(HEADER_SIZE);
        let messageType = header.messageType;

        // TP Handling
        if (
            messageType === MessageType.REQUEST_WITH_TP ||
            messageType === MessageType.REQUEST_NO_RETURN_WITH_TP ||
            messageType === MessageType.NOTIFICATION_WITH_TP ||
            messageType === MessageType.RESPONSE_WITH_TP ||
            messageType === MessageType.ERROR_WITH_TP
        ) {
            if (payload.length < 4) {
                this.logger.log(LogLevel.WARN, 'Runtime', 'Received TP message with payload too short for TP header');
                return;
            }
            try {
                const tpH = TpHeader.deserialize(payload.subarray(0, 4));
                const chunk = payload.subarray(4);

                // Reassemble
                const fullPayload = this.tpReassembler.processSegment({
                    serviceId: header.serviceId,
                    methodId: header.methodId,
                    clientId: header.clientId,
                    sessionId: header.sessionId
                }, tpH, chunk);

                if (fullPayload) {
                    // Reassembly complete
                    payload = fullPayload;
                    // Restore original message type (clear TP bit 0x20)
                    messageType = (messageType & ~0x20);
                } else {
                    // Segment processed but not complete.
                    return;
                }
            } catch (e: any) {
                this.logger.log(LogLevel.ERROR, 'Runtime', `TP Error: ${e.message}`);
                return;
            }
        }

        switch (messageType) {
            case MessageType.REQUEST:
            case MessageType.REQUEST_NO_RETURN:
                this.handleRequest(header, payload, rinfo, ctx);
                break;
            case MessageType.RESPONSE:
            case MessageType.ERROR:
                this.handleResponse(header, payload);
                break;
            case MessageType.NOTIFICATION:
                this.logger.log(LogLevel.DEBUG, 'Runtime',
                    `Notification from service 0x${header.serviceId.toString(16)} event 0x${header.methodId.toString(16)}`);
                break;
        }
    }

    private handleRequest(header: SomeIpHeader, payload: Buffer, rinfo: RemoteInfo, ctx?: InterfaceContext): void {
        const handler = this.handlers.get(header.methodId);
        if (!handler) {
            if (header.messageType === MessageType.REQUEST) {
                const errPacket = buildPacket(
                    header.serviceId, header.methodId, header.sessionId,
                    MessageType.ERROR, Buffer.alloc(0),
                    { returnCode: ReturnCode.UNKNOWN_METHOD }
                );
                const isV6 = rinfo.address.includes(':');
                const transport = rinfo.protocol === 'tcp'
                    ? (isV6 ? ctx?.tcpTransportV6 : ctx?.tcpTransport)
                    : (isV6 ? (ctx?.transportV6 || ctx?.transport) : ctx?.transport);
                if (transport) transport.send(errPacket, rinfo.address, rinfo.port);
            }
            return;
        }

        const responsePayload = handler(header, payload);
        if (responsePayload !== null && header.messageType === MessageType.REQUEST) {

            const MAX_SEG = 1392;
            const isV6 = rinfo.address.includes(':');
            const transport = rinfo.protocol === 'tcp'
                ? (isV6 ? ctx?.tcpTransportV6 : ctx?.tcpTransport)
                : (isV6 ? (ctx?.transportV6 || ctx?.transport) : ctx?.transport);

            if (!transport) return;

            if (responsePayload.length > MAX_SEG) {
                const segments = segmentPayload(responsePayload, MAX_SEG);
                const tpMsgType = MessageType.RESPONSE_WITH_TP;

                for (const seg of segments) {
                    const tpHBuf = seg.header.serialize();
                    const pktPayload = Buffer.concat([tpHBuf, seg.chunk]);

                    const packet = buildPacket(
                        header.serviceId, header.methodId, header.sessionId,
                        tpMsgType,
                        pktPayload,
                        {
                            clientId: header.clientId,
                            protocolVersion: header.protocolVersion,
                            interfaceVersion: header.interfaceVersion,
                            returnCode: ReturnCode.OK
                        }
                    );

                    transport.send(packet, rinfo.address, rinfo.port).catch(e => {
                        this.logger.log(LogLevel.ERROR, 'Runtime', `Failed to send TP segment: ${e.message}`);
                    });
                }
            } else {
                const resPacket = buildPacket(
                    header.serviceId, header.methodId, header.sessionId,
                    MessageType.RESPONSE, responsePayload,
                    { clientId: header.clientId }
                );
                transport.send(resPacket, rinfo.address, rinfo.port);
            }
        }
    }

    private handleResponse(header: SomeIpHeader, payload: Buffer): void {
        const pending = this.pendingRequests.get(String(header.sessionId));
        if (pending) {
            clearTimeout(pending.timer);
            this.pendingRequests.delete(String(header.sessionId));
            pending.resolve({ returnCode: header.returnCode, payload });
        }
    }

    private handleSdMessage(data: Buffer, rinfo: RemoteInfo, ctx?: InterfaceContext): void {
        const payload = data.subarray(HEADER_SIZE);
        if (payload.length < 8) return;

        const entries = parseSdEntries(payload, 4);
        const entriesLen = payload.readUInt32BE(4);
        const options = parseSdOptions(payload, 4 + 4 + entriesLen);

        for (const entry of entries) {
            this.logger.log(LogLevel.DEBUG, 'Runtime', `[DEBUG] Entry: type=${entry.type} sid=${entry.serviceId} inst=${entry.instanceId}`);
            if (entry.type === SdEntryType.OFFER_SERVICE && entry.ttl > 0) {
                if (options.length > 0) {
                    // Check find_on
                    let allowed = true;
                    if (this.config && ctx) {
                        const req = Object.values(this.config.required).find(r => r.serviceId === entry.serviceId);
                        if (req && req.findOn && req.findOn.length > 0) {
                            if (!req.findOn.includes(ctx.alias)) allowed = false;
                        }
                    }

                    if (allowed) {
                        const opt = options[0];
                        const key = `${entry.serviceId}:${entry.instanceId}`;
                        this.remoteServices.set(key, { address: opt.ipAddress, port: opt.port, protocol: opt.protocol, majorVersion: entry.majorVersion, minorVersion: entry.minorVersion });
                        this.logger.log(LogLevel.INFO, 'Runtime', `Discovered service 0x${entry.serviceId.toString(16)} at ${opt.ipAddress}:${opt.port}`);
                    }
                }
            } else if (entry.type === SdEntryType.OFFER_SERVICE && entry.ttl === 0) {
                this.remoteServices.delete(`${entry.serviceId}:${entry.instanceId}`);
            } else if (entry.type === SdEntryType.SUBSCRIBE_EVENTGROUP && entry.ttl > 0) {
                const egId = entry.minorVersion & 0xFFFF;
                const key = `${entry.serviceId}:${egId}`;
                const subs = this.subscribers.get(key) ?? [];
                if (!subs.some(s => s.address === rinfo.address && s.port === rinfo.port)) {
                    subs.push({ address: rinfo.address, port: rinfo.port });
                    this.subscribers.set(key, subs);
                }
            }
        }
    }

    private startCycle(): void {
        const sendOffers = async () => {
            if (!this.config || !this.running) return;
            for (const svc of Object.values(this.config.providing)) {
                for (const alias of (svc.interfaces || [])) {
                    const ctx = this.interfaces.get(alias);
                    if (!ctx) continue;

                    const sdEpKey = this.config.interfaces[alias]?.sd?.endpoint;
                    const sdEp = this.config.interfaces[alias]?.endpoints[sdEpKey];

                    // Resolve offer endpoint
                    const offerEpName = svc.offerOn?.[alias] ?? svc.endpoint;
                    let svcEp = this.config.interfaces[alias]?.endpoints[offerEpName];
                    if (!svcEp) svcEp = this.config.endpoints[offerEpName]; // Fallback to global

                    if (sdEp && svcEp) {
                        // Use actual bound port (resolves ephemeral port 0)
                        const actualPort = this.boundPorts.get(offerEpName) ?? svcEp.port;
                        const packet = buildSdOffer(svc.serviceId, svc.instanceId, svc.majorVersion, svc.minorVersion, svcEp.ip, actualPort, svc.protocol === 'tcp' ? 0x06 : 0x11, this.sessionMgr);
                        await ctx.sdTransport.send(packet, sdEp.ip, sdEp.port);
                    }
                }
            }
        };

        const interval = this.config?.sd.offerInterval ?? 2000;
        setTimeout(() => {
            sendOffers();
            this.offerTimer = setInterval(sendOffers, interval);
        }, this.config?.sd.initialDelay ?? 100);
    }
}
