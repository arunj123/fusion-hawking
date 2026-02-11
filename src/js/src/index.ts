/**
 * Fusion Hawking — JavaScript/TypeScript SOME/IP Stack
 *
 * Public API re-exports. Based on AUTOSAR R22-11.
 * @module
 */

export {
    // Codec
    HEADER_SIZE,
    MessageType,
    ReturnCode,
    SessionIdManager,
    deserializeHeader,
    serializeHeader,
    buildPacket,
    type SomeIpHeader,
    type DeserResult,
    // Primitives
    serializeInt8, serializeInt16, serializeInt32, serializeInt64,
    serializeUInt8, serializeUInt16, serializeUInt32, serializeUInt64,
    serializeFloat32, serializeFloat64,
    serializeBool, serializeString, serializeList,
    deserializeInt8, deserializeInt16, deserializeInt32, deserializeInt64,
    deserializeUInt8, deserializeUInt16, deserializeUInt32, deserializeUInt64,
    deserializeFloat32, deserializeFloat64,
    deserializeBool, deserializeString,
} from './codec.js';

export {
    // SD
    SdEntryType, SdOptionType,
    SD_SERVICE_ID, SD_METHOD_ID, SD_FLAGS_REBOOT,
    IPV4_OPTION_LENGTH, IPV6_OPTION_LENGTH,
    parseSdEntries, parseSdOptions,
    buildSdOffer, buildSdSubscribe,
    type SdEntry, type SdOption,
} from './sd.js';

export {
    // Transport
    UdpTransport,
    type ITransport, type RemoteInfo, type OnMessageCallback,
} from './transport.js';

export {
    // Config
    loadConfig,
    type AppConfig, type EndpointConfig, type ServiceConfigEntry, type SdConfig,
} from './config.js';

export {
    // Logger
    LogLevel, ConsoleLogger,
    type ILogger,
} from './logger.js';

export {
    // Runtime
    SomeIpRuntime,
    type RequestHandler,
} from './runtime.js';
