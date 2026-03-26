import { useEffect, useMemo, useState } from "react";

const moodColors = {
  calm: "#60a5fa",
  focus: "#34d399",
  hype: "#f97316",
};

const initialHistory = [
  { time: "10:00:01", energy: 0.32, focus: 0.58 },
  { time: "10:00:02", energy: 0.41, focus: 0.61 },
  { time: "10:00:03", energy: 0.55, focus: 0.66 },
  { time: "10:00:04", energy: 0.69, focus: 0.70 },
  { time: "10:00:05", energy: 0.74, focus: 0.64 },
  { time: "10:00:06", energy: 0.48, focus: 0.77 },
];

function classifyMood(energy) {
  if (energy < 0.4) return "calm";
  if (energy < 0.7) return "focus";
  return "hype";
}

function getSpotifyPlaylist(mood) {
  const playlists = {
    calm: "Ambient Reset",
    focus: "Deep Focus Flow",
    hype: "High Energy Boost",
  };
  return playlists[mood];
}

function getSunoPrompt(mood) {
  const prompts = {
    calm: "Slow ambient pads with soft textures and peaceful atmosphere",
    focus: "Minimal no-vocal focus music with steady rhythm and low distraction",
    hype: "High-energy techno with driving percussion and exciting momentum",
  };
  return prompts[mood];
}

function formatPercent(value) {
  return `${Math.round(value * 100)}%`;
}

function MetricCard({ label, value, accent }) {
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

function StatusBadge({ text, color }) {
  return (
    <span className="status-badge" style={{ backgroundColor: color }}>
      {text}
    </span>
  );
}

function LogItem({ text, time }) {
  return (
    <div className="log-item">
      <span className="log-time">{time}</span>
      <span>{text}</span>
    </div>
  );
}

function TinyBarChart({ history, metricKey, color, title }) {
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

export default function App() {
  const [connectionStatus, setConnectionStatus] = useState("Connected");
  const [musicMode, setMusicMode] = useState("Spotify");
  const [energy, setEnergy] = useState(0.56);
  const [focus, setFocus] = useState(0.68);
  const [history, setHistory] = useState(initialHistory);
  const [generationStatus, setGenerationStatus] = useState("Idle");
  const [logs, setLogs] = useState([
    { time: "10:00:01", text: "Dashboard started" },
    { time: "10:00:03", text: "Received EEG metrics" },
    { time: "10:00:05", text: "Mood classified as focus" },
  ]);

  const mood = useMemo(() => classifyMood(energy), [energy]);
  const currentPlaylist = useMemo(() => getSpotifyPlaylist(mood), [mood]);
  const currentPrompt = useMemo(() => getSunoPrompt(mood), [mood]);

  useEffect(() => {
    const interval = setInterval(() => {
      const newEnergy = Math.max(0, Math.min(1, energy + (Math.random() - 0.5) * 0.2));
      const newFocus = Math.max(0, Math.min(1, focus + (Math.random() - 0.5) * 0.15));
      const newMood = classifyMood(newEnergy);
      const oldMood = classifyMood(energy);

      const now = new Date();
      const time = now.toLocaleTimeString();

      setEnergy(newEnergy);
      setFocus(newFocus);

      setHistory((prev) => {
        const updated = [...prev, { time, energy: newEnergy, focus: newFocus }];
        return updated.slice(-8);
      });

      if (newMood !== oldMood) {
        setLogs((prev) => [
          { time, text: `Mood changed from ${oldMood} to ${newMood}` },
          ...prev,
        ].slice(0, 8));

        if (musicMode === "Spotify") {
          setLogs((prev) => [
            { time, text: `Spotify switched to "${getSpotifyPlaylist(newMood)}"` },
            ...prev,
          ].slice(0, 8));
        }

        if (musicMode === "Suno") {
          setGenerationStatus("Generating");
          setLogs((prev) => [
            { time, text: `Suno requested a new ${newMood} track` },
            ...prev,
          ].slice(0, 8));

          setTimeout(() => {
            setGenerationStatus("Ready");
            const readyTime = new Date().toLocaleTimeString();
            setLogs((prev) => [
              { time: readyTime, text: "Suno track finished generating" },
              ...prev,
            ].slice(0, 8));
          }, 2500);
        }
      } else {
        setLogs((prev) => [
          { time, text: `Metrics updated: energy ${formatPercent(newEnergy)}, focus ${formatPercent(newFocus)}` },
          ...prev,
        ].slice(0, 8));
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [energy, focus, musicMode]);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>EEG-Powered Music Dashboard</h1>
          <p className="subtitle">
            Frontend dashboard for live brain metrics, mood detection, and music response.
          </p>
        </div>

        <div className="header-statuses">
          <StatusBadge
            text={connectionStatus}
            color={connectionStatus === "Connected" ? "#16a34a" : "#dc2626"}
          />
          <StatusBadge text={`Mode: ${musicMode}`} color="#1d4ed8" />
        </div>
      </header>

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
              <span className={`legend-pill ${mood === "calm" ? "active" : ""}`}>Calm</span>
              <span className={`legend-pill ${mood === "focus" ? "active" : ""}`}>Focus</span>
              <span className={`legend-pill ${mood === "hype" ? "active" : ""}`}>Hype</span>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="music-header">
          <h2>Music Control Panel</h2>
          <div className="button-row">
            <button
              className={musicMode === "Spotify" ? "toggle-btn active-btn" : "toggle-btn"}
              onClick={() => setMusicMode("Spotify")}
            >
              Spotify Mode
            </button>
            <button
              className={musicMode === "Suno" ? "toggle-btn active-btn" : "toggle-btn"}
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

      <section className="charts-grid">
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