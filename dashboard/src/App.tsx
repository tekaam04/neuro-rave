import { useEffect, useMemo, useRef, useState } from "react";
import { useEEGStream } from "./hooks/useEEGStream";
import { EEGChart } from "./components/EEGChart";
import { SAMPLE_RATE, WS_PORT } from "./constants";

const WS_URL = import.meta.env.VITE_WS_URL ?? `ws://localhost:${WS_PORT}/ws`;

const moodColors: Record<string, string> = {
  calm: "#60a5fa",
  focus: "#34d399",
  hype: "#f97316",
};

function getSpotifyPlaylist(mood: string): string {
  const playlists: Record<string, string> = {
    calm: "Ambient Reset",
    focus: "Deep Focus Flow",
    hype: "High Energy Boost",
  };
  return playlists[mood];
}

function getSunoPrompt(mood: string): string {
  const prompts: Record<string, string> = {
    calm: "Slow ambient pads with soft textures and peaceful atmosphere",
    focus:
      "Minimal no-vocal focus music with steady rhythm and low distraction",
    hype: "High-energy techno with driving percussion and exciting momentum",
  };
  return prompts[mood];
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function MetricCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="metric-value">{formatPercent(value)}</div>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${value * 100}%`, backgroundColor: accent }}
        />
      </div>
    </div>
  );
}

function FeatureStatCard({
  label,
  value,
  subtitle,
}: {
  label: string;
  value: number;
  subtitle?: string;
}) {
  const numericValue = Number(value);

  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="big-text">
        {Number.isFinite(numericValue) ? numericValue.toFixed(2) : "—"}
      </div>
      {subtitle ? <div className="small-text">{subtitle}</div> : null}
    </div>
  );
}

function StatusBadge({ text, color }: { text: string; color: string }) {
  return (
    <span className="status-badge" style={{ backgroundColor: color }}>
      {text}
    </span>
  );
}

function LogItem({ text, time }: { text: string; time: string }) {
  return (
    <div className="log-item">
      <span className="log-time">{time}</span>
      <span>{text}</span>
    </div>
  );
}

interface HistoryPoint {
  time: string;
  energy: number;
  focus: number;
}

function TinyBarChart({
  history,
  metricKey,
  color,
  title,
}: {
  history: HistoryPoint[];
  metricKey: "energy" | "focus";
  color: string;
  title: string;
}) {
  const maxHeight = 120;

  return (
    <div className="chart-card">
      <div className="chart-title">{title}</div>
      <div className="chart-bars">
        {history.map((point, index) => (
          <div key={`${metricKey}-${index}`} className="chart-bar-group">
            <div
              className="chart-bar"
              style={{
                height: `${point[metricKey] * maxHeight}px`,
                backgroundColor: color,
              }}
              title={`${point.time} - ${metricKey}: ${formatPercent(point[metricKey])}`}
            />
            <div className="chart-time">{point.time.slice(-2)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyChartCard({ title }: { title: string }) {
  return (
    <div
      className="chart-card"
      style={{
        minHeight: "110px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
      }}
    >
      <div className="chart-title">{title}</div>
      <div className="empty-chart-placeholder">
        <div className="empty-chart-bar" />
        <div className="empty-chart-bar" />
        <div className="empty-chart-bar" />
        <div className="empty-chart-bar" />
      </div>
      <div className="small-text">Waiting for live feature updates...</div>
    </div>
  );
}

export default function App() {
  const { buffer, features, connected } = useEEGStream(WS_URL);

  const [musicMode, setMusicMode] = useState("Spotify");
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [generationStatus, setGenerationStatus] = useState("Idle");
  const [logs, setLogs] = useState([
    { time: new Date().toLocaleTimeString(), text: "Dashboard started" },
  ]);
  const prevMoodRef = useRef<string | null>(null);

  const energy = features?.energy ?? 0;
  const focus = features?.focus ?? 0;
  const mood = features?.mood ?? "calm";
  const connectionStatusText = connected
    ? "Connected to EEG stream"
    : "Connecting to EEG stream...";
  const thetaBetaRatio = features?.theta_beta_ratio ?? 0;
  const alphaSuppression = features?.alpha_suppression ?? 0;
  const neuroFeatureCards = [
    {
      label: "Theta / Beta Ratio",
      value: thetaBetaRatio,
      subtitle: "Attention-related feature from live EEG stream",
    },
    {
      label: "Alpha Suppression",
      value: alphaSuppression,
      subtitle: "Engagement-related feature from live EEG stream",
    },
  ];
  const currentPlaylist = useMemo(() => getSpotifyPlaylist(mood), [mood]);
  const currentPrompt = useMemo(() => getSunoPrompt(mood), [mood]);

  // Build Float32Array[] channels from the FIFO buffer for EEGChart
  const channels: Float32Array[] = buffer
    ? buffer.getData().map((ch) => new Float32Array(ch))
    : [];

  // Update history and logs when features arrive
  useEffect(() => {
    if (!features) return;

    const now = new Date().toLocaleTimeString();

    setHistory((prev) => {
      const updated = [
        ...prev,
        { time: now, energy: features.energy, focus: features.focus },
      ];
      return updated.slice(-8);
    });

    const prevMood = prevMoodRef.current;
    if (prevMood !== null && features.mood !== prevMood) {
      setLogs((prev) =>
        [
          {
            time: now,
            text: `Mood changed from ${prevMood} to ${features.mood}`,
          },
          ...prev,
        ].slice(0, 8),
      );

      if (musicMode === "Spotify") {
        setLogs((prev) =>
          [
            {
              time: now,
              text: `Spotify switched to "${getSpotifyPlaylist(features.mood)}"`,
            },
            ...prev,
          ].slice(0, 8),
        );
      }

      if (musicMode === "Suno") {
        setGenerationStatus("Generating");
        setLogs((prev) =>
          [
            { time: now, text: `Suno requested a new ${features.mood} track` },
            ...prev,
          ].slice(0, 8),
        );

        setTimeout(() => {
          setGenerationStatus("Ready");
          const readyTime = new Date().toLocaleTimeString();
          setLogs((prev) =>
            [
              { time: readyTime, text: "Suno track finished generating" },
              ...prev,
            ].slice(0, 8),
          );
        }, 2500);
      }
    }
    prevMoodRef.current = features.mood;
  }, [features, musicMode]);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>EEG-Powered Music Dashboard</h1>
          <p className="subtitle">
            Frontend dashboard for live brain metrics, mood detection, and music
            response.
          </p>
        </div>

        <div className="header-statuses">
          <StatusBadge
            text={connected ? "Connected" : "Connecting"}
            color={connected ? "#16a34a" : "#dc2626"}
          />
          <StatusBadge text={`Mode: ${musicMode}`} color="#1d4ed8" />
        </div>
      </header>

      {/* ── Live EEG Chart ─────────────────────────────────────────────── */}
      <section className="panel" style={{ marginBottom: 18 }}>
        <h2>Live EEG Stream</h2>
        {channels.length > 0 ? (
          <EEGChart channels={channels} sampleRate={SAMPLE_RATE} />
        ) : (
          <div
            className="small-text"
            style={{ display: "flex", alignItems: "center", gap: "8px" }}
          >
            <span className="pulse-dot" />
            {connectionStatusText}
          </div>
        )}
      </section>

      <section className="top-grid">
        <div className="panel">
          <h2>Live Brain Metrics</h2>
          <div className="metrics-grid">
            <MetricCard label="Energy" value={energy} accent="#f97316" />
            <MetricCard label="Focus" value={focus} accent="#34d399" />
          </div>
        </div>

        <div className="panel">
          <h2>Current Mood</h2>
          <div className="mood-panel">
            <div
              className="mood-circle"
              style={{ backgroundColor: moodColors[mood] }}
            >
              {mood.toUpperCase()}
            </div>
            <p className="mood-description">
              Mood is classified from EEG-derived energy values.
            </p>
            <div className="legend-row">
              <span
                className={`legend-pill ${mood === "calm" ? "active" : ""}`}
              >
                Calm
              </span>
              <span
                className={`legend-pill ${mood === "focus" ? "active" : ""}`}
              >
                Focus
              </span>
              <span
                className={`legend-pill ${mood === "hype" ? "active" : ""}`}
              >
                Hype
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="music-header">
          <h2>Music Control Panel</h2>
          <div className="button-row">
            <button
              className={
                musicMode === "Spotify" ? "toggle-btn active-btn" : "toggle-btn"
              }
              onClick={() => setMusicMode("Spotify")}
            >
              Spotify Mode
            </button>
            <button
              className={
                musicMode === "Suno" ? "toggle-btn active-btn" : "toggle-btn"
              }
              onClick={() => setMusicMode("Suno")}
            >
              Suno Mode
            </button>
          </div>
        </div>

        {musicMode === "Spotify" ? (
          <div className="music-grid">
            <div className="card">
              <div className="card-label">Current Service</div>
              <div className="big-text">Spotify</div>
            </div>
            <div className="card">
              <div className="card-label">Selected Playlist</div>
              <div className="big-text">{currentPlaylist}</div>
            </div>
            <div className="card">
              <div className="card-label">Logic</div>
              <div className="small-text">
                Playlist switches only when mood changes.
              </div>
            </div>
          </div>
        ) : (
          <div className="music-grid">
            <div className="card">
              <div className="card-label">Current Service</div>
              <div className="big-text">Suno</div>
            </div>
            <div className="card">
              <div className="card-label">Prompt</div>
              <div className="small-text">{currentPrompt}</div>
            </div>
            <div className="card">
              <div className="card-label">Generation Status</div>
              <div className="big-text">{generationStatus}</div>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Neuro Features</h2>
        <div className="music-grid">
          {neuroFeatureCards.map((feature) => (
            <FeatureStatCard
              key={feature.label}
              label={feature.label}
              value={feature.value}
              subtitle={feature.subtitle}
            />
          ))}
        </div>
      </section>

      <section className="charts-grid">
        {history.length > 0 ? (
          <>
            <TinyBarChart
              history={history}
              metricKey="energy"
              color="#f97316"
              title="Energy History"
            />
            <TinyBarChart
              history={history}
              metricKey="focus"
              color="#34d399"
              title="Focus History"
            />
          </>
        ) : (
          <>
            <EmptyChartCard title="Energy History" />
            <EmptyChartCard title="Focus History" />
          </>
        )}
      </section>

      <section className="panel">
        <h2>Recent Activity Log</h2>
        <div className="log-list">
          {logs.map((log, index) => (
            <LogItem key={index} time={log.time} text={log.text} />
          ))}
        </div>
      </section>
    </div>
  );
}
