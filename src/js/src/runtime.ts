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

import {
    HEADER_SIZE,
    MessageType,
    ReturnCode,
    SessionIdManager,
    deserializeHeader,
    buildPacket,
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
import { UdpTransport, type ITransport, type RemoteInfo } from './transport.js';
import { type ILogger, LogLevel, ConsoleLogger } from './logger.js';
import { type AppConfig, loadConfig } from './config.js';

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

export class SomeIpRuntime {
    private transport: ITransport;
    private sdTransport: ITransport | null = null;
    private sessionMgr = new SessionIdManager();
    private logger: ILogger;
    private config: AppConfig | null = null;

    public getLogger(): ILogger {
        return this.logger;
    }

    // Service management
    private handlers = new Map<number, RequestHandler>(); // methodId → handler
    private remoteServices = new Map<string, RemoteService>(); // "serviceId:instanceId" → remote
    private pendingRequests = new Map<string, PendingRequest>(); // "sessionId" → pending
    private subscribers = new Map<string, Subscriber[]>(); // "serviceId:eventgroupId" → subscribers

    // SD timers
    private offerTimer: ReturnType<typeof setInterval> | null = null;
    private running = false;

    constructor(logger?: ILogger) {
        this.logger = logger ?? new ConsoleLogger();
        this.transport = new UdpTransport('udp4', this.logger);
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
     * Start the runtime: bind transport, set up SD, start offering.
     */
    async start(bindAddress: string = '127.0.0.1', bindPort: number = 0): Promise<void> {
        this.running = true;

        // Bind main transport
        await this.transport.bind(bindAddress, bindPort);
        this.logger.log(LogLevel.INFO, 'Runtime',
            `Started on ${this.transport.localAddress}:${this.transport.localPort}`);

        // Set up message handling
        this.transport.onMessage((data, rinfo) => this.handleMessage(data, rinfo));

        // Start SD if config available
        if (this.config) {
            await this.startServiceDiscovery();
        }
    }

    /** Stop the runtime and clean up resources. */
    stop(): void {
        this.running = false;
        if (this.offerTimer) {
            clearInterval(this.offerTimer);
            this.offerTimer = null;
        }
        // Reject all pending requests
        for (const [key, pending] of this.pendingRequests) {
            clearTimeout(pending.timer);
            pending.reject(new Error('Runtime stopped'));
        }
        this.pendingRequests.clear();
        this.transport.close();
        this.sdTransport?.close();
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
        timeoutMs: number = 3000,
    ): Promise<SomeIpResponse> {
        const sessionId = this.sessionMgr.nextSessionId(serviceId, methodId);
        const packet = buildPacket(serviceId, methodId, sessionId, MessageType.REQUEST, payload);

        return new Promise<SomeIpResponse>((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pendingRequests.delete(String(sessionId));
                reject(new Error(`Request timeout for session ${sessionId}`));
            }, timeoutMs);

            this.pendingRequests.set(String(sessionId), { resolve, reject, timer });
            this.transport.send(packet, targetAddress, targetPort).catch(reject);
        });
    }

    /**
     * Send a fire-and-forget request (no response expected).
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
        await this.transport.send(packet, targetAddress, targetPort);
    }

    /**
     * Send a notification (event) to all subscribers.
     */
    async sendNotification(
        serviceId: number,
        eventId: number,
        payload: Buffer,
    ): Promise<void> {
        // Iterate over all eventgroups for this service
        for (const [key, subs] of this.subscribers) {
            const [sid] = key.split(':').map(Number);
            if (sid !== serviceId) continue;

            const sessionId = this.sessionMgr.nextSessionId(serviceId, eventId);
            const packet = buildPacket(serviceId, eventId, sessionId, MessageType.NOTIFICATION, payload);

            for (const sub of subs) {
                await this.transport.send(packet, sub.address, sub.port);
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
        if (!this.sdTransport || !this.config) {
            this.logger.log(LogLevel.WARN, 'Runtime', 'Cannot subscribe: SD not running');
            return;
        }

        const sdEp = this.config.endpoints[this.config.sd.multicastEndpoint];
        if (!sdEp) return;

        const packet = buildSdSubscribe(serviceId, instanceId, 1, eventgroupId, this.sessionMgr);
        await this.sdTransport.send(packet, sdEp.ip, sdEp.port);
        this.logger.log(LogLevel.INFO, 'Runtime',
            `Subscribed to service 0x${serviceId.toString(16)} eventgroup 0x${eventgroupId.toString(16)}`);
    }

    /** Get a discovered remote service by service ID. */
    getRemoteService(serviceId: number, instanceId: number = 0xFFFF): RemoteService | undefined {
        if (instanceId === 0xFFFF) {
            // Find any instance
            for (const [key, svc] of this.remoteServices) {
                if (key.startsWith(`${serviceId}:`)) return svc;
            }
            return undefined;
        }
        return this.remoteServices.get(`${serviceId}:${instanceId}`);
    }

    /** Get the bound port (useful when binding to port 0). */
    get localPort(): number { return this.transport.localPort; }
    get localAddress(): string { return this.transport.localAddress; }

    // ── Private Methods ──

    private handleMessage(data: Buffer, rinfo: RemoteInfo): void {
        const header = deserializeHeader(data);
        if (!header) {
            this.logger.log(LogLevel.WARN, 'Runtime', `Received packet too short (${data.length} bytes)`);
            return;
        }

        // SD message?
        if (header.serviceId === SD_SERVICE_ID && header.methodId === SD_METHOD_ID) {
            this.handleSdMessage(data, rinfo);
            return;
        }

        const payload = data.subarray(HEADER_SIZE);

        switch (header.messageType) {
            case MessageType.REQUEST:
            case MessageType.REQUEST_NO_RETURN:
                this.handleRequest(header, payload, rinfo);
                break;
            case MessageType.RESPONSE:
            case MessageType.ERROR:
                this.handleResponse(header, payload);
                break;
            case MessageType.NOTIFICATION:
                this.logger.log(LogLevel.DEBUG, 'Runtime',
                    `Notification from service 0x${header.serviceId.toString(16)} event 0x${header.methodId.toString(16)}`);
                break;
            default:
                this.logger.log(LogLevel.WARN, 'Runtime',
                    `Unknown message type 0x${header.messageType.toString(16)}`);
        }
    }

    private handleRequest(header: SomeIpHeader, payload: Buffer, rinfo: RemoteInfo): void {
        this.logger.log(LogLevel.DEBUG, 'Runtime',
            `Request: service=0x${header.serviceId.toString(16)} method=0x${header.methodId.toString(16)} from ${rinfo.address}:${rinfo.port}`);

        const handler = this.handlers.get(header.methodId);
        if (!handler) {
            this.logger.log(LogLevel.WARN, 'Runtime',
                `No handler for method 0x${header.methodId.toString(16)}`);
            // Send error response if it's a REQUEST (not fire-and-forget)
            if (header.messageType === MessageType.REQUEST) {
                const errPacket = buildPacket(
                    header.serviceId, header.methodId, header.sessionId,
                    MessageType.ERROR, Buffer.alloc(0),
                    { returnCode: ReturnCode.UNKNOWN_METHOD }
                );
                this.transport.send(errPacket, rinfo.address, rinfo.port);
            }
            return;
        }

        const responsePayload = handler(header, payload);
        if (responsePayload !== null && header.messageType === MessageType.REQUEST) {
            const resPacket = buildPacket(
                header.serviceId, header.methodId, header.sessionId,
                MessageType.RESPONSE, responsePayload,
            );
            this.transport.send(resPacket, rinfo.address, rinfo.port);
        }
    }

    private handleResponse(header: SomeIpHeader, payload: Buffer): void {
        const pending = this.pendingRequests.get(String(header.sessionId));
        if (pending) {
            clearTimeout(pending.timer);
            this.pendingRequests.delete(String(header.sessionId));
            pending.resolve({ returnCode: header.returnCode, payload });
        } else {
            this.logger.log(LogLevel.WARN, 'Runtime',
                `Unexpected response for session ${header.sessionId}`);
        }
    }

    private handleSdMessage(data: Buffer, rinfo: RemoteInfo): void {
        const payload = data.subarray(HEADER_SIZE);
        if (payload.length < 8) return;

        // Skip flags (4 bytes), parse entries
        const entries = parseSdEntries(payload, 4);
        const entriesLen = payload.readUInt32BE(4);
        const optionsOffset = 4 + 4 + entriesLen;
        const options = parseSdOptions(payload, optionsOffset);

        for (const entry of entries) {
            if (entry.type === SdEntryType.OFFER_SERVICE && entry.ttl > 0) {
                // Process offer — extract endpoint from options
                if (options.length > 0) {
                    const opt = options[0];
                    const key = `${entry.serviceId}:${entry.instanceId}`;
                    this.remoteServices.set(key, {
                        address: opt.ipAddress,
                        port: opt.port,
                        protocol: opt.protocol,
                        majorVersion: entry.majorVersion,
                        minorVersion: entry.minorVersion,
                    });
                    this.logger.log(LogLevel.INFO, 'Runtime',
                        `Discovered service 0x${entry.serviceId.toString(16)} at ${opt.ipAddress}:${opt.port}`);
                }
            } else if (entry.type === SdEntryType.OFFER_SERVICE && entry.ttl === 0) {
                // Stop offer
                const key = `${entry.serviceId}:${entry.instanceId}`;
                this.remoteServices.delete(key);
                this.logger.log(LogLevel.INFO, 'Runtime',
                    `Service 0x${entry.serviceId.toString(16)} stopped`);
            } else if (entry.type === SdEntryType.SUBSCRIBE_EVENTGROUP && entry.ttl > 0) {
                // Subscribe
                const egId = entry.minorVersion & 0xFFFF;
                const key = `${entry.serviceId}:${egId}`;
                const subs = this.subscribers.get(key) ?? [];
                subs.push({ address: rinfo.address, port: rinfo.port });
                this.subscribers.set(key, subs);
                this.logger.log(LogLevel.INFO, 'Runtime',
                    `Subscriber added for service 0x${entry.serviceId.toString(16)} eventgroup ${egId}`);
            }
        }
    }

    private async startServiceDiscovery(): Promise<void> {
        if (!this.config) return;

        const sdEp = this.config.endpoints[this.config.sd.multicastEndpoint];
        if (!sdEp) {
            this.logger.log(LogLevel.WARN, 'Runtime', 'No SD multicast endpoint configured');
            return;
        }

        // Create SD transport
        this.sdTransport = new UdpTransport('udp4', this.logger);
        try {
            await (this.sdTransport as UdpTransport).bind('0.0.0.0', sdEp.port);
            await (this.sdTransport as UdpTransport).joinMulticast(sdEp.ip);
            (this.sdTransport as UdpTransport).setMulticastLoopback(true);
        } catch (err: any) {
            this.logger.log(LogLevel.WARN, 'Runtime', `SD transport setup failed: ${err.message}`);
            return;
        }

        // Handle incoming SD messages
        this.sdTransport.onMessage((data, rinfo) => this.handleMessage(data, rinfo));

        // Start periodic offering
        const sendOffers = async () => {
            if (!this.config || !this.running) return;
            for (const [, svc] of Object.entries(this.config.providing)) {
                const ep = this.config.endpoints[svc.endpoint];
                if (!ep) continue;
                const packet = buildSdOffer(
                    svc.serviceId, svc.instanceId,
                    svc.majorVersion, svc.minorVersion,
                    ep.ip, ep.port,
                    svc.protocol === 'tcp' ? 0x06 : 0x11,
                    this.sessionMgr,
                );
                await this.sdTransport!.send(packet, sdEp.ip, sdEp.port);
            }
        };

        // Initial offer after delay
        setTimeout(() => {
            sendOffers();
            this.offerTimer = setInterval(sendOffers, this.config!.sd.offerInterval);
        }, this.config.sd.initialDelay);
    }
}
