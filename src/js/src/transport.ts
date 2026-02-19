/**
 * Fusion Hawking Transport Layer — Node.js UDP Adapter
 *
 * Provides the ITransport interface and a UDP implementation using
 * Node.js `dgram` module. The interface is designed to be swappable
 * for testing or alternative runtimes (Deno, Bun, Electron).
 * @module
 */

import dgram from 'node:dgram';
import * as net from 'node:net';
import * as os from 'node:os';
import { ILogger, LogLevel } from './logger.js';

/** Remote address info. */
export interface RemoteInfo {
    address: string;
    port: number;
    family: 'IPv4' | 'IPv6';
    protocol: 'udp' | 'tcp';
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
    private socket!: dgram.Socket;
    private messageCallbacks: OnMessageCallback[] = [];
    private _localAddress: string = '';
    private _localPort: number = 0;

    constructor(
        private family: 'udp4' | 'udp6' = 'udp4',
        private logger?: ILogger,
        private reuseAddr: boolean = os.platform() === 'win32', // Default true on Windows
    ) {
        this._createSocket();
    }

    private _createSocket() {
        if (this.socket) {
            try {
                this.socket.removeAllListeners();
                this.socket.close();
            } catch {
                // Ignore close errors
            }
        }
        this.socket = dgram.createSocket({
            type: this.family,
            reuseAddr: this.reuseAddr,
        });

        this.socket.on('message', (msg, rinfo) => {
            if (process.env.FUSION_PACKET_DUMP === "1") {
                console.log(`[Transport] RECV ${msg.length} bytes from ${rinfo.address}:${rinfo.port}`);
            }
            const remote: RemoteInfo = {
                address: rinfo.address,
                port: rinfo.port,
                family: rinfo.family as 'IPv4' | 'IPv6',
                protocol: 'udp',
            };
            for (const cb of this.messageCallbacks) {
                cb(msg, remote);
            }
        });

        this.socket.on('error', (err) => {
            if (this._localPort !== 0 || err.message.includes('bind')) {
                this.logger?.log(LogLevel.ERROR, 'Transport', `[${this.family}] Socket error: ${err.message}`);
            }
        });
    }

    async bind(address: string, port: number): Promise<void> {
        this._localPort = port;
        try {
            await this._doBind(address, port);
        } catch (err: any) {
            if (err.code === 'UNKNOWN' || err.code === 'EACCES') {
                const isWindows = os.platform() === 'win32';
                this.logger?.log(LogLevel.WARN, 'Transport', `Bind to ${address}:${port} failed (${err.code}), retrying with wildcard...`);

                this._createSocket();
                try {
                    await this._doBind(isWindows ? '0.0.0.0' : '0.0.0.0', port);
                } catch (err2: any) {
                    if (isWindows && (err2.code === 'UNKNOWN' || err2.code === 'EACCES') && port === 0) {
                        this.logger?.log(LogLevel.WARN, 'Transport', `Wildcard bind also failed, retrying with random high port...`);
                        // Final fallback: try a random ephemeral port manually
                        for (let attempt = 0; attempt < 5; attempt++) {
                            this._createSocket();
                            const randomPort = 40000 + Math.floor(Math.random() * 20000);
                            try {
                                await this._doBind('0.0.0.0', randomPort);
                                return;
                            } catch {
                                // Try next random port
                            }
                        }
                    }
                    throw err2;
                }
            } else {
                throw err;
            }
        }
    }

    private async _doBind(address: string, port: number): Promise<void> {
        return new Promise((resolve, reject) => {
            const errorHandler = (err: Error) => {
                this.logger?.log(LogLevel.ERROR, 'Transport', `Bind error for ${address}:${port}: ${err.message}`);
                reject(err);
            };

            this.socket.once('error', errorHandler);

            try {
                this.socket.bind({
                    address,
                    port,
                    exclusive: false // Use non-exclusive for better Windows behavior
                }, () => {
                    this.socket.removeListener('error', errorHandler);
                    const addr = this.socket.address();
                    this._localAddress = addr.address;
                    this._localPort = addr.port;
                    this.logger?.log(LogLevel.INFO, 'Transport', `Bound (${this.family}) to ${this._localAddress}:${this._localPort}`);
                    resolve();
                });
            } catch (err: any) {
                this.socket.removeListener('error', errorHandler);
                reject(err);
            }
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
            console.log(`[Transport] Joined multicast ${multicastAddress} on interface ${iface || 'default'}`);
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

    /** Set the interface for outgoing multicast packets. */
    setMulticastInterface(address: string): void {
        try {
            this.socket.setMulticastInterface(address);
        } catch (err: any) {
            this.logger?.log(LogLevel.WARN, 'Transport', `Failed to set multicast interface: ${err.message}`);
        }
    }
}

/** TCP transport implementation using Node.js net. */
export class TcpTransport implements ITransport {
    private socket: net.Socket | null = null;
    private messageCallbacks: OnMessageCallback[] = [];
    private _localAddress: string = '';
    private _localPort: number = 0;
    private buffer: Buffer = Buffer.alloc(0);

    constructor(
        private logger?: ILogger
    ) { }

    async connect(address: string, port: number): Promise<void> {
        return new Promise((resolve, reject) => {
            this.socket = net.connect({ host: address, port }, () => {
                this._localAddress = this.socket!.localAddress || '';
                this._localPort = this.socket!.localPort || 0;
                this.logger?.log(LogLevel.INFO, 'Transport', `Connected to TCP ${address}:${port}`);
                resolve();
            });

            this.socket.on('data', (data) => this._handleData(data, { address, port, family: address.includes(':') ? 'IPv6' : 'IPv4', protocol: 'tcp' }));
            this.socket.on('error', (err) => {
                this.logger?.log(LogLevel.ERROR, 'Transport', `TCP error: ${err.message}`);
                reject(err);
            });
            this.socket.on('close', () => {
                this.logger?.log(LogLevel.INFO, 'Transport', `TCP connection closed`);
            });
        });
    }

    private _handleData(data: Buffer, rinfo: RemoteInfo) {
        this.buffer = Buffer.concat([this.buffer, data]);
        while (this.buffer.length >= 16) {
            const length = this.buffer.readUInt32BE(4);
            const totalLength = length + 8;
            if (this.buffer.length >= totalLength) {
                const packet = this.buffer.subarray(0, totalLength);
                this.buffer = this.buffer.subarray(totalLength);
                for (const cb of this.messageCallbacks) {
                    cb(packet, rinfo);
                }
            } else {
                break;
            }
        }
    }

    async bind(_address: string, _port: number): Promise<void> {
        // TCP Client doesn't typically bind to a specific local port for SOME/IP
        // But we can implement it if needed. For now, it's a no-op or connect fallback.
    }

    async send(data: Buffer, _address: string, _port: number): Promise<void> {
        return new Promise((resolve, reject) => {
            if (!this.socket) {
                reject(new Error('TCP socket not connected'));
                return;
            }
            this.socket.write(data, (err) => {
                if (err) reject(err);
                else resolve();
            });
        });
    }

    onMessage(callback: OnMessageCallback): void {
        this.messageCallbacks.push(callback);
    }

    close(): void {
        this.socket?.destroy();
        this.socket = null;
    }

    get localAddress(): string { return this._localAddress; }
    get localPort(): number { return this._localPort; }
}

/** TCP Server transport implementation. */
export class TcpServerTransport implements ITransport {
    private server: net.Server | null = null;
    private clients: Map<string, net.Socket> = new Map();
    private messageCallbacks: OnMessageCallback[] = [];
    private _localAddress: string = '';
    private _localPort: number = 0;
    private buffers: Map<net.Socket, Buffer> = new Map();

    constructor(
        private logger?: ILogger
    ) { }

    async bind(address: string, port: number): Promise<void> {
        return new Promise((resolve, reject) => {
            this.server = net.createServer((socket) => {
                const remoteKey = `${socket.remoteAddress}:${socket.remotePort}`;
                this.clients.set(remoteKey, socket);
                this.buffers.set(socket, Buffer.alloc(0));

                this.logger?.log(LogLevel.INFO, 'Transport', `New TCP client: ${remoteKey}`);

                socket.on('data', (data) => this._handleClientData(socket, data));
                socket.on('error', (err) => {
                    this.logger?.log(LogLevel.WARN, 'Transport', `TCP client ${remoteKey} error: ${err.message}`);
                });
                socket.on('close', () => {
                    this.clients.delete(remoteKey);
                    this.buffers.delete(socket);
                    this.logger?.log(LogLevel.INFO, 'Transport', `TCP client ${remoteKey} disconnected`);
                });
            });

            this.server.on('error', (err) => {
                this.logger?.log(LogLevel.ERROR, 'Transport', `TCP Server error: ${err.message}`);
                reject(err);
            });

            this.server.listen(port, address, () => {
                const addr = this.server!.address() as net.AddressInfo;
                this._localAddress = addr.address;
                this._localPort = addr.port;
                this.logger?.log(LogLevel.INFO, 'Transport', `TCP Server listening on ${this._localAddress}:${this._localPort}`);
                resolve();
            });
        });
    }

    private _handleClientData(socket: net.Socket, data: Buffer) {
        let buffer = this.buffers.get(socket) || Buffer.alloc(0);
        buffer = Buffer.concat([buffer, data]);

        while (buffer.length >= 16) {
            const length = buffer.readUInt32BE(4);
            const totalLength = length + 8;
            if (buffer.length >= totalLength) {
                const packet = buffer.subarray(0, totalLength);
                buffer = buffer.subarray(totalLength);

                const rinfo: RemoteInfo = {
                    address: socket.remoteAddress || '',
                    port: socket.remotePort || 0,
                    family: (socket.remoteFamily === 'IPv6' ? 'IPv6' : 'IPv4') as 'IPv4' | 'IPv6',
                    protocol: 'tcp'
                };

                for (const cb of this.messageCallbacks) {
                    cb(packet, rinfo);
                }
            } else {
                break;
            }
        }
        this.buffers.set(socket, buffer);
    }

    async send(data: Buffer, address: string, port: number): Promise<void> {
        // Find existing connection to this address:port
        // SOME/IP over TCP usually keeps connections open.
        // If not found, we might need to connect? But Server usually only sends to connected clients.
        for (const [key, socket] of this.clients) {
            if (socket.remoteAddress === address && socket.remotePort === port) {
                return new Promise((resolve, reject) => {
                    socket.write(data, (err) => {
                        if (err) reject(err);
                        else resolve();
                    });
                });
            }
        }

        // Fallback: This part is tricky. If we are a "Server" but need to send to a "Client"
        // we haven't seen, we usually don't.
        this.logger?.log(LogLevel.WARN, 'Transport', `TCP Server cannot send to ${address}:${port}: No active connection`);
    }

    onMessage(callback: OnMessageCallback): void {
        this.messageCallbacks.push(callback);
    }

    close(): void {
        for (const socket of this.clients.values()) {
            socket.destroy();
        }
        this.clients.clear();
        this.server?.close();
    }

    get localAddress(): string { return this._localAddress; }
    get localPort(): number { return this._localPort; }
}
