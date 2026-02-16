
import { SomeIpRuntime, LogLevel } from 'fusion-hawking';
import * as path from 'path';

// Mock FusedTrack structure (would typically be generated)
interface FusedTrack {
    track_id: number;
    position_x: number;
    position_y: number;
    velocity_x: number;
    velocity_y: number;
    confidence: number;
}

class AdasApplication {
    private trackCount = 0;
    private warningDistance = 10.0;

    constructor(private runtime: SomeIpRuntime) { }

    public onTrackUpdate(tracks: FusedTrack[]) {
        this.trackCount += tracks.length;

        this.runtime.getLogger().log(
            LogLevel.INFO,
            "ADAS",
            `Received ${tracks.length} fused tracks (total: ${this.trackCount})`
        );

        for (const track of tracks) {
            const distance = Math.sqrt(Math.pow(track.position_x, 2) + Math.pow(track.position_y, 2));
            if (distance < this.warningDistance) {
                this.runtime.getLogger().log(
                    LogLevel.WARN,
                    "ADAS",
                    `** COLLISION WARNING: Track ${track.track_id} at ${distance.toFixed(1)}m! **`
                );
            }
        }
    }
}

async function main() {
    console.log("=== ADAS Application Demo (JS/TS) ===");

    // Path to config from command line or default
    const configPath = process.argv[2] || path.resolve('../config.json');
    const runtime = new SomeIpRuntime();
    await runtime.loadConfigFile(configPath);

    runtime.getLogger().log(LogLevel.INFO, "Main", "ADAS Application starting...");
    runtime.start();

    const adas = new AdasApplication(runtime);

    // Subscribe to FusionService events (0x7002: Service, 1: Instance, 1: EventGroup)
    runtime.subscribeEventgroup(0x7002, 1, 1, 100);

    runtime.getLogger().log(LogLevel.INFO, "Main", "Subscribed to FusionService events. Waiting...");

    // Mock loop to simulate runtime listening
    let iteration = 0;
    const interval = setInterval(() => {
        iteration++;

        // Mock receiving tracks periodically for demo visual
        if (iteration % 4 === 0) {
            const demoTracks: FusedTrack[] = [
                { track_id: 1, position_x: 15.0, position_y: 2.0, velocity_x: 0, velocity_y: 0, confidence: 0.9 },
                { track_id: 2, position_x: 8.5, position_y: 1.0, velocity_x: 0, velocity_y: 0, confidence: 0.85 },
            ];
            adas.onTrackUpdate(demoTracks);
        }

        if (iteration >= 6) {
            runtime.getLogger().log(LogLevel.INFO, "Main", "Demo completed (6 iterations)");
            clearInterval(interval);
            runtime.stop();
        }
    }, 500);
}

main().catch(err => console.error(err));
