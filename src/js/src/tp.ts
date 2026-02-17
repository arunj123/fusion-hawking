import { HEADER_SIZE } from './codec.js';

export class TpHeader {
    constructor(
        public offset: number, // In units of 16 bytes
        public moreSegments: boolean
    ) { }

    static deserialize(buf: Buffer): TpHeader {
        if (buf.length < 4) throw new Error("TP Header too short");
        const val = buf.readUInt32BE(0);
        const offset = val >>> 4;
        const moreSegments = (val & 0x01) !== 0;
        return new TpHeader(offset, moreSegments);
    }

    serialize(): Buffer {
        const buf = Buffer.alloc(4);
        // Offset is 28 bits, shifted left by 4. More segments is last bit.
        const val = (this.offset << 4) | (this.moreSegments ? 1 : 0);
        buf.writeUInt32BE(val >>> 0, 0); // Ensure unsigned
        return buf;
    }
}

/**
 * Splits a payload into TP segments.
 * @param payload The full payload to split.
 * @param maxPayloadPerSegment Max bytes per segment (must be multiple of 16).
 * @returns Array of [TpHeader, Buffer] tuples.
 */
export function segmentPayload(payload: Buffer, maxPayloadPerSegment: number = 1392): { header: TpHeader, chunk: Buffer }[] {
    const segments: { header: TpHeader, chunk: Buffer }[] = [];
    let remaining = payload.length;
    let currentOffset = 0; // In bytes

    while (remaining > 0) {
        let chunkSize = Math.min(remaining, maxPayloadPerSegment);

        // If not the last segment, length must be multiple of 16
        if (remaining > maxPayloadPerSegment) {
            chunkSize = Math.floor(chunkSize / 16) * 16;
        }

        const chunk = payload.subarray(currentOffset, currentOffset + chunkSize);
        remaining -= chunkSize;

        const moreSegments = remaining > 0;
        // Offset in TpHeader is in units of 16 bytes
        const tpOffset = currentOffset / 16;

        segments.push({
            header: new TpHeader(tpOffset, moreSegments),
            chunk: Buffer.from(chunk) // Copy to be safe
        });

        currentOffset += chunkSize;
    }

    return segments;
}

export class TpReassembler {
    // Key: "serviceId:methodId:clientId:sessionId"
    private buffers = new Map<string, {
        segments: Map<number, Buffer>, // offset -> data
        lastOffsetReceived: boolean,
        expectedTotalLength: number
    }>();

    private MAX_PAYLOAD_SIZE = 10 * 1024 * 1024; // 10MB limit

    /**
     * Process a TP segment.
     * @returns The full reassembled payload if complete, null otherwise.
     */
    processSegment(
        key: { serviceId: number, methodId: number, clientId: number, sessionId: number },
        header: TpHeader,
        payload: Buffer
    ): Buffer | null {
        const k = `${key.serviceId}:${key.methodId}:${key.clientId}:${key.sessionId}`;

        let session = this.buffers.get(k);
        if (!session) {
            session = { segments: new Map(), lastOffsetReceived: false, expectedTotalLength: 0 };
            this.buffers.set(k, session);
        }

        // Validate payload length alignment (must be multiple of 16 unless it's the last one)
        // Standard says: "The length of the payload of a segment... shall be a multiple of 16 bytes.
        // Exception: The last segment..."
        if (header.moreSegments && (payload.length % 16 !== 0)) {
            console.warn(`[TP] Dropping invalid segment: More=1 but len=${payload.length} not aligned.`);
            this.buffers.delete(k);
            return null;
        }

        session.segments.set(header.offset, payload);

        if (!header.moreSegments) {
            session.lastOffsetReceived = true;
            // The byte offset of this last chunk starts at header.offset * 16
            // Total length = (header.offset * 16) + payload.length
            session.expectedTotalLength = (header.offset * 16) + payload.length;
        }

        // Check completion
        if (session.lastOffsetReceived) {
            // Check if we have all bytes covered
            let currentOffset = 0;
            let totalLen = 0;
            // Simplified check: Use a sorted approach or just track holes?
            // Since we stored by unit-offset, we can iterate.
            // But Map iteration order is insertion order in JS (mostly).
            // Let's sort keys.
            const sortedOffsets = Array.from(session.segments.keys()).sort((a, b) => a - b);

            // Check contiguity
            // First offset must be 0?
            if (sortedOffsets.length === 0 || sortedOffsets[0] !== 0) return null;

            let contiguous = true;
            let byteOffset = 0;

            for (const off of sortedOffsets) {
                if (off * 16 !== byteOffset) {
                    contiguous = false;
                    break;
                }
                const chunk = session.segments.get(off)!;
                byteOffset += chunk.length;
            }

            if (contiguous && byteOffset === session.expectedTotalLength) {
                // Reassemble
                const chunks = sortedOffsets.map(off => session.segments.get(off)!);
                const full = Buffer.concat(chunks);
                this.buffers.delete(k);
                return full;
            }
        }

        return null;
    }
}
