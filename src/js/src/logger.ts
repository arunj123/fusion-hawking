/**
 * Fusion Hawking Logger — SOME/IP Logging Interface
 * 
 * Runtime-agnostic logging. Works on Node.js, Deno, Bun.
 * @module
 */

/** Log severity levels matching Rust/Python/C++ runtimes. */
export enum LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARN = 2,
    ERROR = 3,
}

/** Abstract logger interface — implement for custom backends (DLT, file, etc.). */
export interface ILogger {
    log(level: LogLevel, tag: string, message: string): void;
}

/** Default console logger with colored output. */
export class ConsoleLogger implements ILogger {
    constructor(private minLevel: LogLevel = LogLevel.DEBUG) { }

    log(level: LogLevel, tag: string, message: string): void {
        if (level < this.minLevel) return;
        const prefix = ['DBG', 'INF', 'WRN', 'ERR'][level] ?? 'UNK';
        const timestamp = new Date().toISOString().slice(11, 23);
        console.log(`[${timestamp}] [${prefix}] [${tag}] ${message}`);
    }
}
