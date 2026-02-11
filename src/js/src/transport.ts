/**
 * Fusion Hawking Transport Layer — Node.js UDP Adapter
 *
 * Provides the ITransport interface and a UDP implementation using
 * Node.js `dgram` module. The interface is designed to be swappable
 * for testing or alternative runtimes (Deno, Bun, Electron).
 * @module
 */

import dgram from 'node:dgram';
import { ILogger, LogLevel } from './logger.js';

/** Remote address info. */
export interface RemoteInfo {
    address: string;
    port: number;
    family: 'IPv4' | 'IPv6';
}

/** Message received callback. */
export type OnMessageCallback = (data: Buffer, rinfo: RemoteInfo) => void;

/** Abstract transport interface. */
export interface ITransport {
    bind(address: string, port: number): Promise<void>;
    send(data: Buffer, address: string, port: number): Promise<void>;
    onMessage(callback: OnMessageCallback): void;
    close(): void;
    readonly localAddress: string;
    readonly localPort: number;
}

/** UDP transport implementation using Node.js dgram. */
export class UdpTransport implements ITransport {
    private socket: dgram.Socket;
    private messageCallbacks: OnMessageCallback[] = [];
    private _localAddress: string = '';
    private _localPort: number = 0;

    constructor(
        private family: 'udp4' | 'udp6' = 'udp4',
        private logger?: ILogger,
    ) {
        this.socket = dgram.createSocket({
            type: family,
            reuseAddr: true,
        });

        this.socket.on('message', (msg, rinfo) => {
            const remote: RemoteInfo = {
                address: rinfo.address,
                port: rinfo.port,
                family: rinfo.family as 'IPv4' | 'IPv6',
            };
            for (const cb of this.messageCallbacks) {
                cb(msg, remote);
            }
        });

        this.socket.on('error', (err) => {
            this.logger?.log(LogLevel.ERROR, 'Transport', `Socket error: ${err.message}`);
        });
    }

    async bind(address: string, port: number): Promise<void> {
        return new Promise((resolve, reject) => {
            this.socket.bind(port, address, () => {
                const addr = this.socket.address();
                this._localAddress = addr.address;
                this._localPort = addr.port;
                this.logger?.log(LogLevel.INFO, 'Transport', `Bound to ${this._localAddress}:${this._localPort}`);
                resolve();
            });
            this.socket.once('error', reject);
        });
    }

    async send(data: Buffer, address: string, port: number): Promise<void> {
        return new Promise((resolve, reject) => {
            this.socket.send(data, 0, data.length, port, address, (err) => {
                if (err) reject(err);
                else resolve();
            });
        });
    }

    onMessage(callback: OnMessageCallback): void {
        this.messageCallbacks.push(callback);
    }

    close(): void {
        try {
            this.socket.close();
        } catch {
            // Socket may already be closed
        }
    }

    get localAddress(): string { return this._localAddress; }
    get localPort(): number { return this._localPort; }

    /** Join a multicast group (for SD). */
    async joinMulticast(multicastAddress: string, iface?: string): Promise<void> {
        try {
            this.socket.addMembership(multicastAddress, iface);
            this.logger?.log(LogLevel.INFO, 'Transport', `Joined multicast ${multicastAddress}`);
        } catch (err: any) {
            this.logger?.log(LogLevel.WARN, 'Transport', `Failed to join multicast: ${err.message}`);
        }
    }

    /** Set multicast TTL. */
    setMulticastTtl(ttl: number): void {
        this.socket.setMulticastTTL(ttl);
    }

    /** Enable/disable multicast loopback. */
    setMulticastLoopback(enabled: boolean): void {
        this.socket.setMulticastLoopback(enabled);
    }
}
