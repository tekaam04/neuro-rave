import { useEEGStream } from './hooks/useEEGStream'
import { EEGChart } from './components/EEGChart'

/** WebSocket URL — override with VITE_WS_URL env var in .env.local */
const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8765/ws'

export default function App(): JSX.Element {
  const { buffer, connected } = useEEGStream(WS_URL)

  return (
    <div style={{ padding: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
        <h1 style={{ fontSize: '1.2rem', letterSpacing: '0.1em' }}>NEURO-RAVE</h1>
        <span style={{ color: connected ? '#00ff88' : '#ff6b6b', fontSize: '0.85rem' }}>
          {connected ? '● live' : '○ disconnected'}
        </span>
        {buffer && (
          <span style={{ color: '#888', fontSize: '0.75rem', marginLeft: 'auto' }}>
            {buffer.n_channels} ch · {buffer.sample_rate} Hz
          </span>
        )}
      </div>

      {buffer ? (
        <EEGChart channels={buffer.channels} sampleRate={buffer.sample_rate} />
      ) : (
        <p style={{ color: '#555' }}>Waiting for stream…</p>
      )}
    </div>
  )
}
