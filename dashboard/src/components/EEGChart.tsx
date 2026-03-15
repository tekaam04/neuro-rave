import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

// ── Types ──────────────────────────────────────────────────────────────────────

interface EEGChartProps {
  channels:    Float32Array[]  // one per channel, length = display window
  sampleRate:  number
}

// ── Constants ──────────────────────────────────────────────────────────────────

const CHANNEL_COLORS: string[] = [
  '#00ff88', '#ff6b6b', '#4ecdc4', '#ffe66d',
  '#a29bfe', '#fd79a8', '#fdcb6e', '#6c5ce7',
]

const CHART_HEIGHT_PER_CHANNEL = 80  // px

// ── Component ──────────────────────────────────────────────────────────────────

export function EEGChart({ channels, sampleRate }: EEGChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null)
  const plotRef      = useRef<uPlot | null>(null)

  const n     = channels[0]?.length ?? 0
  const nCh   = channels.length

  /** Relative time axis: most recent sample = 0, oldest = -(window - 1) / sr */
  const times = new Float64Array(n).map((_, i) => (i - n + 1) / sampleRate)

  // Build or rebuild the plot when channel count changes.
  useEffect(() => {
    if (!containerRef.current || nCh === 0) return

    plotRef.current?.destroy()

    const opts: uPlot.Options = {
      width:  containerRef.current.clientWidth,
      height: CHART_HEIGHT_PER_CHANNEL * nCh,
      cursor: { show: false },
      legend: { show: false },
      series: [
        {},  // x-axis placeholder
        ...channels.map((_, i) => ({
          label:  `Ch ${i}`,
          stroke: CHANNEL_COLORS[i % CHANNEL_COLORS.length],
          width:  1,
          points: { show: false },
        })),
      ],
      axes: [
        { label: 'time (s)', stroke: '#888', ticks: { stroke: '#333' } },
        { label: 'raw',      stroke: '#888', ticks: { stroke: '#333' }, size: 50 },
      ],
      scales: { x: { time: false } },
    }

    const data: uPlot.AlignedData = [times, ...channels]

    plotRef.current = new uPlot(opts, data, containerRef.current)

    return (): void => { plotRef.current?.destroy() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nCh])  // rebuild only when channel count changes

  // Every render: push new data without rebuilding the plot.
  useEffect(() => {
    plotRef.current?.setData([times, ...channels])
  })

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', background: '#111', borderRadius: 4, padding: 8 }}
    />
  )
}
