// Add new packet types here as the server grows.
// Mirror changes in src/streaming/packets.py.

export interface BasePacket {
  type:      string
  timestamp: number
}

export interface RawPacket extends BasePacket {
  type:     'raw'
  channels: number[][]  // columnar: one array of samples per channel
}

export interface FeaturesPacket extends BasePacket {
  type:  'features'
  alpha: number
  beta:  number
}

export type AnyPacket = RawPacket | FeaturesPacket
