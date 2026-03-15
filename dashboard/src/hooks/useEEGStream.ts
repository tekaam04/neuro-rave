import { useCallback, useEffect, useRef, useState } from 'react'

/** How many seconds of data to keep in the rolling display buffer. */
const DISPLAY_SECONDS = 5

// ── Types ──────────────────────────────────────────────────────────────────────

/** JSON packet sent by the Python WebSocket server once per second. */
interface EEGPacket {
  timestamp:   number      // LSL timestamp of the first sample in the chunk
  sample_rate: number
  n_channels:  number
  channels:    number[][]  // columnar: one array of samples per channel
}

/** Rolling display buffer exposed to components. */
export interface EEGBuffer {
  /** One Float32Array per channel, length = DISPLAY_SECONDS × sample_rate */
  channels:    Float32Array[]
  /** LSL timestamp of the most recent packet */
  timestamp:   number
  n_channels:  number
  sample_rate: number
}

export interface UseEEGStreamResult {
  buffer:      EEGBuffer | null
  connected:   boolean
}

// ── Hook ───────────────────────────────────────────────────────────────────────

export function useEEGStream(url: string): UseEEGStreamResult {
  const [buffer,    setBuffer]    = useState<EEGBuffer | null>(null)
  const [connected, setConnected] = useState(false)

  /** Persisted rolling arrays — mutated in place, never re-allocated unless
   *  channel count or sample rate changes. */
  const rollingRef = useRef<Float32Array[] | null>(null)
  const wsRef      = useRef<WebSocket | null>(null)

  const onPacket = useCallback((packet: EEGPacket): void => {
    const windowSize = DISPLAY_SECONDS * packet.sample_rate

    // (Re-)initialise rolling buffer when channel count or window size changes.
    if (
      !rollingRef.current ||
      rollingRef.current.length !== packet.n_channels ||
      rollingRef.current[0].length !== windowSize
    ) {
      rollingRef.current = Array.from(
        { length: packet.n_channels },
        () => new Float32Array(windowSize),
      )
    }

    const rolling = rollingRef.current

    for (let ch = 0; ch < packet.n_channels; ch++) {
      const incoming = packet.channels[ch]
      const n        = incoming.length
      const buf      = rolling[ch]

      if (n >= windowSize) {
        // Incoming chunk is larger than the display window — keep the tail.
        buf.set(new Float32Array(incoming.slice(-windowSize)))
      } else {
        // Shift existing data left by n, then append new samples at the end.
        buf.copyWithin(0, n)
        buf.set(incoming, windowSize - n)
      }
    }

    // Shallow-copy each channel array so React sees new references.
    setBuffer({
      channels:    rolling.map(ch => ch.slice()),
      timestamp:   packet.timestamp,
      n_channels:  packet.n_channels,
      sample_rate: packet.sample_rate,
    })
  }, [])

  useEffect(() => {
    function connect(): void {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = (): void => setConnected(true)

      ws.onclose = (): void => {
        setConnected(false)
        // Auto-reconnect after 2 s.
        setTimeout(connect, 2000)
      }

      ws.onerror = (): void => ws.close()

      ws.onmessage = (ev: MessageEvent<string>): void => {
        onPacket(JSON.parse(ev.data) as EEGPacket)
      }
    }

    connect()

    return (): void => { wsRef.current?.close() }
  }, [url, onPacket])

  return { buffer, connected }
}
